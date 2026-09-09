package com.multyfi.intraday.mobile

import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStreamReader
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder

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
        quote(accessToken, "NIFTY").lastPrice > 0.0
    }.getOrDefault(false)

    fun generateAccessToken(apiKey: String, totp: String): String {
        require(apiKey.isNotBlank()) { "Groww API key is missing" }
        require(totp.matches(Regex("\\d{6}"))) { "Enter the current 6-digit TOTP" }
        val conn = connection(URL("$BASE/token/api/access"), "POST", apiKey).apply {
            doOutput = true
            setRequestProperty("Content-Type", "application/json")
        }
        return try {
            val payload = JSONObject().put("key_type", "totp").put("totp", totp).toString()
            conn.outputStream.use { it.write(payload.toByteArray(Charsets.UTF_8)) }
            val body = read(conn)
            if (conn.responseCode !in 200..299) error("Groww HTTP ${conn.responseCode}: ${body.take(200)}")
            val root = JSONObject(body)
            root.optString("token").ifBlank {
                root.optJSONObject("payload")?.optString("token").orEmpty()
            }.ifBlank { error("Groww did not return an access token") }
        } finally {
            conn.disconnect()
        }
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
