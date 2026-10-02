package com.suhas.iposentinel

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

data class ApiResult(
    val ok: Boolean,
    val statusCode: Int,
    val body: String,
    val error: String? = null
)

data class ConnectionStatus(
    val secretStoreReady: Boolean = false,
    val growwConfigured: Boolean = false,
    val expectedStaticIp: String? = null,
    val staticIpConfirmed: Boolean = false,
    val error: String? = null
)

data class ValidationStatus(
    val growwAuthOk: Boolean = false,
    val detectedEgressIp: String? = null,
    val expectedStaticIp: String? = null,
    val staticIpMatches: Boolean = false,
    val staticIpConfirmed: Boolean = false,
    val secretStoreReady: Boolean = false,
    val liveExecutionReady: Boolean = false,
    val growwError: String? = null,
    val egressError: String? = null
)

class BackendApi(
    private val baseUrl: String,
    private val adminKey: String
) {
    private fun endpoint(path: String): String =
        baseUrl.trim().trimEnd('/') + path

    suspend fun saveGrowwSettings(
        totpToken: String,
        totpSecret: String,
        expectedStaticIp: String,
        staticIpConfirmed: Boolean
    ): ApiResult {
        val payload = JSONObject()
            .put("totp_token", totpToken.trim())
            .put("totp_secret", totpSecret.replace(" ", "").trim())
            .put("expected_static_ip", expectedStaticIp.trim())
            .put("static_ip_confirmed", staticIpConfirmed)
            .toString()
        return request("POST", "/settings/groww", payload)
    }

    suspend fun fetchStatus(): Pair<ApiResult, ConnectionStatus?> {
        val result = request("GET", "/settings/status", null)
        if (!result.ok) return result to null
        val json = JSONObject(result.body)
        return result to ConnectionStatus(
            secretStoreReady = json.optBoolean("secret_store_ready", false),
            growwConfigured = json.optBoolean("groww_configured", false),
            expectedStaticIp = json.optString("expected_static_ip").ifBlank { null },
            staticIpConfirmed = json.optBoolean("static_ip_confirmed", false),
            error = json.optString("error").ifBlank { null }
        )
    }

    suspend fun validate(): Pair<ApiResult, ValidationStatus?> {
        val result = request("POST", "/settings/validate", "{}")
        if (!result.ok) return result to null
        val json = JSONObject(result.body)
        return result to ValidationStatus(
            growwAuthOk = json.optBoolean("groww_auth_ok", false),
            detectedEgressIp = json.optString("detected_egress_ip").ifBlank { null },
            expectedStaticIp = json.optString("expected_static_ip").ifBlank { null },
            staticIpMatches = json.optBoolean("static_ip_matches", false),
            staticIpConfirmed = json.optBoolean("static_ip_confirmed", false),
            secretStoreReady = json.optBoolean("secret_store_ready", false),
            liveExecutionReady = json.optBoolean("live_execution_ready", false),
            growwError = json.optString("groww_error").ifBlank { null },
            egressError = json.optString("egress_error").ifBlank { null }
        )
    }

    private suspend fun request(method: String, path: String, body: String?): ApiResult =
        withContext(Dispatchers.IO) {
            try {
                val url = URL(endpoint(path))
                val connection = (url.openConnection() as HttpURLConnection).apply {
                    requestMethod = method
                    connectTimeout = 8_000
                    readTimeout = 15_000
                    setRequestProperty("Accept", "application/json")
                    setRequestProperty("X-IPO-Sentinel-Admin-Key", adminKey)
                    if (body != null) {
                        doOutput = true
                        setRequestProperty("Content-Type", "application/json")
                    }
                }

                if (body != null) {
                    connection.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
                }

                val code = connection.responseCode
                val stream = if (code in 200..299) connection.inputStream else connection.errorStream
                val text = stream?.bufferedReader()?.use { it.readText() }.orEmpty()
                val parsedError = if (code in 200..299) null else extractError(text)
                connection.disconnect()
                ApiResult(code in 200..299, code, text, parsedError)
            } catch (exc: Exception) {
                ApiResult(false, 0, "", exc.message ?: exc::class.java.simpleName)
            }
        }

    private fun extractError(body: String): String {
        if (body.isBlank()) return "Backend request failed"
        return try {
            JSONObject(body).optString("detail").ifBlank { body.take(300) }
        } catch (_: Exception) {
            body.take(300)
        }
    }
}
