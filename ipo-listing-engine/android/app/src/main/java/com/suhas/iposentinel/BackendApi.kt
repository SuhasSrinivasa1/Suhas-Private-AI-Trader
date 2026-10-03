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

data class LiveStateStatus(
    val enabled: Boolean = false,
    val budgetRupees: Int = 100_000,
    val updatedAt: String? = null,
    val eventId: Long = 0L
)

data class OrderLifecycleEvent(
    val id: Long,
    val timestamp: String,
    val eventType: String,
    val symbol: String? = null,
    val side: String? = null,
    val quantity: Int? = null,
    val price: Double? = null,
    val orderId: String? = null,
    val message: String? = null
)

data class OrderEventBatch(
    val events: List<OrderLifecycleEvent>,
    val lastId: Long
)

data class ResearchCandidate(
    val candidateId: String,
    val lifecycleState: String,
    val symbol: String?,
    val companyName: String,
    val listingDate: String?,
    val issueStartDate: String?,
    val issueEndDate: String?,
    val officialIssueId: String?,
    val isin: String?,
    val board: String?,
    val isSme: Boolean,
    val issueStatus: String?,
    val nseListingConfirmed: Boolean,
    val growwSymbol: String?,
    val growwSeries: String?,
    val buyAllowed: Boolean,
    val sellAllowed: Boolean,
    val symbolResolved: Boolean,
    val growwResolutionStatus: String,
    val resolutionStatus: String
)

data class ResearchPlan(
    val generatedAt: String? = null,
    val sourceReady: Boolean = false,
    val researchHealth: String = "UNKNOWN",
    val calendarReady: Boolean = false,
    val nextTradingDay: String? = null,
    val candidateCount: Int = 0,
    val nseIdentityConfirmedCount: Int = 0,
    val growwResolvedCount: Int = 0,
    val growwPendingCount: Int = 0,
    val nextTradingDayCandidates: List<ResearchCandidate> = emptyList(),
    val weekCandidates: List<ResearchCandidate> = emptyList(),
    val allKnownCandidates: List<ResearchCandidate> = emptyList(),
    val errors: List<String> = emptyList()
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

    suspend fun fetchResearchPlan(): Pair<ApiResult, ResearchPlan?> {
        val result = request("GET", "/research/plan", null)
        if (!result.ok) return result to null
        val json = JSONObject(result.body)

        fun parseCandidate(obj: JSONObject): ResearchCandidate =
            ResearchCandidate(
                candidateId = obj.optString("candidate_id"),
                lifecycleState = obj.optString("lifecycle_state", "RESEARCHING"),
                symbol = obj.optString("symbol").ifBlank { null },
                companyName = obj.optString("company_name"),
                listingDate = obj.optString("listing_date").ifBlank { null },
                issueStartDate = obj.optString("issue_start_date").ifBlank { null },
                issueEndDate = obj.optString("issue_end_date").ifBlank { null },
                officialIssueId = obj.optString("official_issue_id").ifBlank { null },
                isin = obj.optString("isin").ifBlank { null },
                board = obj.optString("board").ifBlank { null },
                isSme = obj.optBoolean("is_sme", false),
                issueStatus = obj.optString("issue_status").ifBlank { null },
                nseListingConfirmed = obj.optBoolean("nse_listing_confirmed", false),
                growwSymbol = obj.optString("groww_symbol").ifBlank { null },
                growwSeries = obj.optString("groww_series").ifBlank { null },
                buyAllowed = obj.optBoolean("buy_allowed", false),
                sellAllowed = obj.optBoolean("sell_allowed", false),
                symbolResolved = obj.optBoolean("symbol_resolved", false),
                growwResolutionStatus = obj.optString("groww_resolution_status", "UNKNOWN"),
                resolutionStatus = obj.optString("resolution_status", "UNKNOWN")
            )

        fun parseArray(name: String): List<ResearchCandidate> {
            val arr = json.optJSONArray(name) ?: return emptyList()
            return buildList {
                for (i in 0 until arr.length()) {
                    add(parseCandidate(arr.getJSONObject(i)))
                }
            }
        }

        val errorsJson = json.optJSONArray("errors")
        val errors = buildList {
            if (errorsJson != null) {
                for (i in 0 until errorsJson.length()) add(errorsJson.optString(i))
            }
        }

        return result to ResearchPlan(
            generatedAt = json.optString("generated_at").ifBlank { null },
            sourceReady = json.optBoolean("source_ready", false),
            researchHealth = json.optString("research_health", "UNKNOWN"),
            calendarReady = json.optBoolean("calendar_ready", false),
            nextTradingDay = json.optString("next_trading_day").ifBlank { null },
            candidateCount = json.optInt("candidate_count", 0),
            nseIdentityConfirmedCount = json.optInt("nse_identity_confirmed_count", 0),
            growwResolvedCount = json.optInt("groww_resolved_count", 0),
            growwPendingCount = json.optInt("groww_pending_count", 0),
            nextTradingDayCandidates = parseArray("next_trading_day_candidates"),
            weekCandidates = parseArray("week_candidates"),
            allKnownCandidates = parseArray("all_known_candidates"),
            errors = errors
        )
    }

    suspend fun refreshResearchPlan(): Pair<ApiResult, ResearchPlan?> {
        val result = request("POST", "/research/refresh", "{}")
        if (!result.ok) return result to null
        val json = JSONObject(result.body)

        fun parseCandidate(obj: JSONObject): ResearchCandidate =
            ResearchCandidate(
                candidateId = obj.optString("candidate_id"),
                lifecycleState = obj.optString("lifecycle_state", "RESEARCHING"),
                symbol = obj.optString("symbol").ifBlank { null },
                companyName = obj.optString("company_name"),
                listingDate = obj.optString("listing_date").ifBlank { null },
                issueStartDate = obj.optString("issue_start_date").ifBlank { null },
                issueEndDate = obj.optString("issue_end_date").ifBlank { null },
                officialIssueId = obj.optString("official_issue_id").ifBlank { null },
                isin = obj.optString("isin").ifBlank { null },
                board = obj.optString("board").ifBlank { null },
                isSme = obj.optBoolean("is_sme", false),
                issueStatus = obj.optString("issue_status").ifBlank { null },
                nseListingConfirmed = obj.optBoolean("nse_listing_confirmed", false),
                growwSymbol = obj.optString("groww_symbol").ifBlank { null },
                growwSeries = obj.optString("groww_series").ifBlank { null },
                buyAllowed = obj.optBoolean("buy_allowed", false),
                sellAllowed = obj.optBoolean("sell_allowed", false),
                symbolResolved = obj.optBoolean("symbol_resolved", false),
                growwResolutionStatus = obj.optString("groww_resolution_status", "UNKNOWN"),
                resolutionStatus = obj.optString("resolution_status", "UNKNOWN")
            )

        fun parseArray(name: String): List<ResearchCandidate> {
            val arr = json.optJSONArray(name) ?: return emptyList()
            return buildList {
                for (i in 0 until arr.length()) add(parseCandidate(arr.getJSONObject(i)))
            }
        }

        val errorsJson = json.optJSONArray("errors")
        val errors = buildList {
            if (errorsJson != null) {
                for (i in 0 until errorsJson.length()) add(errorsJson.optString(i))
            }
        }

        return result to ResearchPlan(
            generatedAt = json.optString("generated_at").ifBlank { null },
            sourceReady = json.optBoolean("source_ready", false),
            researchHealth = json.optString("research_health", "UNKNOWN"),
            calendarReady = json.optBoolean("calendar_ready", false),
            nextTradingDay = json.optString("next_trading_day").ifBlank { null },
            candidateCount = json.optInt("candidate_count", 0),
            nseIdentityConfirmedCount = json.optInt("nse_identity_confirmed_count", 0),
            growwResolvedCount = json.optInt("groww_resolved_count", 0),
            growwPendingCount = json.optInt("groww_pending_count", 0),
            nextTradingDayCandidates = parseArray("next_trading_day_candidates"),
            weekCandidates = parseArray("week_candidates"),
            allKnownCandidates = parseArray("all_known_candidates"),
            errors = errors
        )
    }

    suspend fun fetchLiveState(): Pair<ApiResult, LiveStateStatus?> {
        val result = request("GET", "/live/state", null)
        if (!result.ok) return result to null
        val json = JSONObject(result.body)
        return result to LiveStateStatus(
            enabled = json.optBoolean("enabled", false),
            budgetRupees = json.optInt("budget_rupees", 100_000),
            updatedAt = json.optString("updated_at").ifBlank { null },
            eventId = json.optLong("event_id", 0L)
        )
    }

    suspend fun setLiveState(enabled: Boolean, budgetRupees: Int): Pair<ApiResult, LiveStateStatus?> {
        val payload = JSONObject()
            .put("enabled", enabled)
            .put("budget_rupees", budgetRupees)
            .toString()
        val result = request("POST", "/live/state", payload)
        if (!result.ok) return result to null
        val json = JSONObject(result.body)
        return result to LiveStateStatus(
            enabled = json.optBoolean("enabled", false),
            budgetRupees = json.optInt("budget_rupees", budgetRupees),
            updatedAt = json.optString("updated_at").ifBlank { null },
            eventId = json.optLong("event_id", 0L)
        )
    }

    suspend fun fetchOrderEvents(afterId: Long): Pair<ApiResult, OrderEventBatch?> {
        val result = request("GET", "/events/orders?after_id=" + afterId + "&limit=100", null)
        if (!result.ok) return result to null
        val json = JSONObject(result.body)
        val arr = json.optJSONArray("events")
        val events = buildList {
            if (arr != null) {
                for (i in 0 until arr.length()) {
                    val obj = arr.getJSONObject(i)
                    add(
                        OrderLifecycleEvent(
                            id = obj.optLong("id", 0L),
                            timestamp = obj.optString("timestamp"),
                            eventType = obj.optString("event_type"),
                            symbol = obj.optString("symbol").ifBlank { null },
                            side = obj.optString("side").ifBlank { null },
                            quantity = if (obj.isNull("quantity")) null else obj.optInt("quantity"),
                            price = if (obj.isNull("price")) null else obj.optDouble("price"),
                            orderId = obj.optString("order_id").ifBlank { null },
                            message = obj.optString("message").ifBlank { null }
                        )
                    )
                }
            }
        }
        return result to OrderEventBatch(
            events = events,
            lastId = json.optLong("last_id", afterId)
        )
    }

    suspend fun exportAudit(days: Int = 7): ApiResult {
        return request("GET", "/audit/export?days=" + days.coerceIn(1, 31), null)
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
