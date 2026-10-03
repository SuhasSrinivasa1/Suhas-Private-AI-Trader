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

data class StrategyFamilyStats(
    val familyId: String,
    val name: String,
    val phase: String,
    val description: String,
    val trades: Int,
    val winRatePct: Double,
    val expectancyBps: Double,
    val profitFactor: Double,
    val maxDrawdownBps: Double,
    val last20NetBps: Double,
    val status: String,
    val rankingScore: Double
)

data class StrategySummary(
    val totalStrategyFamilies: Int = 0,
    val testedFamilies: Int = 0,
    val champions: Int = 0,
    val challengers: Int = 0,
    val untestedFamilies: Int = 0,
    val topFive: List<StrategyFamilyStats> = emptyList(),
    val families: List<StrategyFamilyStats> = emptyList(),
    val rankingNote: String = ""
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

class BackendApi {
    private val baseUrl: String = BuildConfig.IPO_SENTINEL_API_URL.trim().trimEnd('/')
    private val deviceKey: String = BuildConfig.IPO_SENTINEL_DEVICE_KEY

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

    suspend fun fetchStrategySummary(): Pair<ApiResult, StrategySummary?> {
        val result = request("GET", "/strategies/summary", null)
        if (!result.ok) return result to null
        val json = JSONObject(result.body)

        fun parseFamily(obj: JSONObject): StrategyFamilyStats =
            StrategyFamilyStats(
                familyId = obj.optString("family_id"),
                name = obj.optString("name"),
                phase = obj.optString("phase"),
                description = obj.optString("description"),
                trades = obj.optInt("trades", 0),
                winRatePct = obj.optDouble("win_rate_pct", 0.0),
                expectancyBps = obj.optDouble("expectancy_bps", 0.0),
                profitFactor = obj.optDouble("profit_factor", 0.0),
                maxDrawdownBps = obj.optDouble("max_drawdown_bps", 0.0),
                last20NetBps = obj.optDouble("last_20_net_bps", 0.0),
                status = obj.optString("status", "RESEARCH"),
                rankingScore = obj.optDouble("ranking_score", 0.0)
            )

        val topFiveJson = json.optJSONArray("top_five")
        val familiesJson = json.optJSONArray("families")
        val topFive = buildList {
            if (topFiveJson != null) {
                for (i in 0 until topFiveJson.length()) {
                    add(parseFamily(topFiveJson.getJSONObject(i)))
                }
            }
        }
        val families = buildList {
            if (familiesJson != null) {
                for (i in 0 until familiesJson.length()) {
                    add(parseFamily(familiesJson.getJSONObject(i)))
                }
            }
        }

        return result to StrategySummary(
            totalStrategyFamilies = json.optInt("total_strategy_families", 0),
            testedFamilies = json.optInt("tested_families", 0),
            champions = json.optInt("champions", 0),
            challengers = json.optInt("challengers", 0),
            untestedFamilies = json.optInt("untested_families", 0),
            topFive = topFive,
            families = families,
            rankingNote = json.optString("ranking_note")
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
            if (baseUrl.isBlank()) {
                return@withContext ApiResult(
                    ok = false,
                    statusCode = 0,
                    body = "",
                    error = "Trading service is not provisioned in this build"
                )
            }
            if (!baseUrl.startsWith("https://")) {
                return@withContext ApiResult(
                    ok = false,
                    statusCode = 0,
                    body = "",
                    error = "Trading service configuration is invalid"
                )
            }

            try {
                val url = URL(baseUrl + path)
                val connection = (url.openConnection() as HttpURLConnection).apply {
                    requestMethod = method
                    connectTimeout = 8_000
                    readTimeout = 15_000
                    setRequestProperty("Accept", "application/json")
                    if (deviceKey.isNotBlank()) {
                        setRequestProperty("X-IPO-Sentinel-Device-Key", deviceKey)
                    }
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
        if (body.isBlank()) return "Trading service request failed"
        return try {
            JSONObject(body).optString("detail").ifBlank { body.take(300) }
        } catch (_: Exception) {
            body.take(300)
        }
    }
}
