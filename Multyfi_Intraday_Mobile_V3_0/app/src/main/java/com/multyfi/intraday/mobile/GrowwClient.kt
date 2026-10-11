package com.multyfi.intraday.mobile

import org.json.JSONObject
import java.io.BufferedReader
import java.io.ByteArrayOutputStream
import java.io.InputStreamReader
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import java.security.MessageDigest
import java.util.Locale
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

object GrowwClient {
    private const val BASE = "https://api.groww.in/v1"

    private fun connection(url: URL, method: String, bearer: String = ""): HttpURLConnection {
        return (url.openConnection() as HttpURLConnection).apply {
            requestMethod = method
            connectTimeout = 7000
            readTimeout = 7000
            setRequestProperty("Accept", "application/json")
            setRequestProperty("X-API-VERSION", "1.0")
            if (bearer.isNotBlank()) setRequestProperty("Authorization", "Bearer $bearer")
            useCaches = false
        }
    }

    private fun read(conn: HttpURLConnection): String {
        val stream = if (conn.responseCode in 200..299) conn.inputStream else conn.errorStream
        return BufferedReader(InputStreamReader(stream ?: return "")).use { it.readText() }
    }

    private fun extractAccessToken(body: String): String {
        val root = JSONObject(body)
        return root.optString("token").ifBlank {
            root.optJSONObject("payload")?.optString("token").orEmpty()
        }.ifBlank { error("Groww did not return an access token") }
    }

    fun quote(accessToken: String, symbol: String): GrowwQuote {
        require(accessToken.isNotBlank()) { "Groww access token is missing" }
        val encoded = URLEncoder.encode(symbol.uppercase(), "UTF-8")
        val url = URL("$BASE/live-data/quote?exchange=NSE&segment=CASH&trading_symbol=$encoded")
        val conn = connection(url, "GET", accessToken)
        return try {
            val body = read(conn)
            if (conn.responseCode !in 200..299) error("Groww HTTP ${conn.responseCode}: ${body.take(180)}")
            val root = JSONObject(body)
            if (!root.optString("status").equals("SUCCESS", true)) error("Groww response: ${body.take(180)}")
            val p = root.getJSONObject("payload")
            GrowwQuote(
                symbol = symbol.uppercase(),
                lastPrice = p.optDouble("last_price", 0.0),
                volume = p.optLong("volume", 0L),
                averagePrice = p.optDouble("average_price", 0.0),
                bidPrice = p.optDouble("bid_price", 0.0),
                offerPrice = p.optDouble("offer_price", 0.0),
                rawStatus = root.optString("status", "")
            ).also { if (it.lastPrice <= 0.0) error("Groww quote returned no valid LTP for $symbol") }
        } finally {
            conn.disconnect()
        }
    }

    fun validateAccessToken(accessToken: String): Boolean = runCatching {
        require(accessToken.isNotBlank())
        val conn = connection(URL("$BASE/user/detail"), "GET", accessToken)
        try {
            val body = read(conn)
            if (conn.responseCode !in 200..299) return@runCatching false
            JSONObject(body).optString("status").equals("SUCCESS", true)
        } finally {
            conn.disconnect()
        }
    }.getOrDefault(false)

    fun generateAccessTokenWithApproval(apiKey: String, apiSecret: String): String {
        require(apiKey.isNotBlank()) { "Groww API key is missing" }
        require(apiSecret.isNotBlank()) { "Groww API secret is missing" }
        val timestamp = (System.currentTimeMillis() / 1000L).toString()
        val checksumBytes = MessageDigest.getInstance("SHA-256")
            .digest((apiSecret.trim() + timestamp).toByteArray(Charsets.UTF_8))
        val checksum = checksumBytes.joinToString("") { "%02x".format(Locale.US, it.toInt() and 0xff) }
        val conn = connection(URL("$BASE/token/api/access"), "POST", apiKey.trim()).apply {
            doOutput = true
            setRequestProperty("Content-Type", "application/json")
        }
        return try {
            val payload = JSONObject()
                .put("key_type", "approval")
                .put("checksum", checksum)
                .put("timestamp", timestamp)
                .toString()
            conn.outputStream.use { it.write(payload.toByteArray(Charsets.UTF_8)) }
            val body = read(conn)
            if (conn.responseCode !in 200..299) error("Groww HTTP ${conn.responseCode}: ${body.take(240)}")
            extractAccessToken(body)
        } finally {
            conn.disconnect()
        }
    }

    fun generateAccessTokenWithTotp(totpToken: String, totpSecret: String): String {
        require(totpToken.isNotBlank()) { "Groww TOTP token is missing" }
        require(totpSecret.isNotBlank()) { "Groww TOTP secret is missing" }
        val currentTotp = currentTotp(totpSecret)
        val conn = connection(URL("$BASE/token/api/access"), "POST", totpToken.trim()).apply {
            doOutput = true
            setRequestProperty("Content-Type", "application/json")
        }
        return try {
            val payload = JSONObject().put("key_type", "totp").put("totp", currentTotp).toString()
            conn.outputStream.use { it.write(payload.toByteArray(Charsets.UTF_8)) }
            val body = read(conn)
            if (conn.responseCode !in 200..299) error("Groww HTTP ${conn.responseCode}: ${body.take(240)}")
            extractAccessToken(body)
        } finally {
            conn.disconnect()
        }
    }

    private fun currentTotp(secret: String, nowMillis: Long = System.currentTimeMillis()): String {
        val key = decodeBase32(secret)
        val counter = (nowMillis / 1000L) / 30L
        val data = ByteArray(8)
        var value = counter
        for (i in 7 downTo 0) {
            data[i] = (value and 0xffL).toByte()
            value = value ushr 8
        }
        val mac = Mac.getInstance("HmacSHA1")
        mac.init(SecretKeySpec(key, "HmacSHA1"))
        val hash = mac.doFinal(data)
        val offset = hash.last().toInt() and 0x0f
        val binary = ((hash[offset].toInt() and 0x7f) shl 24) or
            ((hash[offset + 1].toInt() and 0xff) shl 16) or
            ((hash[offset + 2].toInt() and 0xff) shl 8) or
            (hash[offset + 3].toInt() and 0xff)
        return "%06d".format(Locale.US, binary % 1_000_000)
    }

    private fun decodeBase32(raw: String): ByteArray {
        val alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
        val clean = raw.trim().replace(" ", "").replace("-", "").trimEnd('=').uppercase(Locale.US)
        require(clean.isNotBlank()) { "Groww TOTP secret is empty" }
        val out = ByteArrayOutputStream()
        var buffer = 0
        var bitsLeft = 0
        clean.forEach { ch ->
            val v = alphabet.indexOf(ch)
            require(v >= 0) { "Groww TOTP secret is not valid Base32" }
            buffer = (buffer shl 5) or v
            bitsLeft += 5
            while (bitsLeft >= 8) {
                bitsLeft -= 8
                out.write((buffer shr bitsLeft) and 0xff)
                buffer = if (bitsLeft == 0) 0 else buffer and ((1 shl bitsLeft) - 1)
            }
        }
        return out.toByteArray().also { require(it.isNotEmpty()) { "Groww TOTP secret is invalid" } }
    }

    fun detectPublicIp(): String {
        val conn = connection(URL("https://api.ipify.org?format=json"), "GET")
        return try {
            val body = read(conn)
            if (conn.responseCode !in 200..299) error("IP detection failed: HTTP ${conn.responseCode}")
            JSONObject(body).optString("ip").ifBlank { error("No public IP returned") }
        } finally {
            conn.disconnect()
        }
    }
}
