package com.multyfi.intraday.mobile

import android.content.Context
import android.provider.Settings
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.UUID

class AppRepository(private val context: Context) {
    private val prefs = context.getSharedPreferences("multyfi_v3", Context.MODE_PRIVATE)
    private val secret = SecretStore(context)
    private val candidatesFile = File(context.filesDir, "candidates.json")
    private val tradesFile = File(context.filesDir, "trade_events.jsonl")
    private val activityFile = File(context.filesDir, "activity.jsonl")
    private val learningFile = File(context.filesDir, "learning_history.jsonl")
    private val ticksDir = File(context.filesDir, "ticks").apply { mkdirs() }
    private val sdf = SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.US)

    @Synchronized
    fun currentConfig(): SignalConfig = SignalConfig(
        prefs.getString("cfg_enter", "0.68")?.toDoubleOrNull() ?: 0.68,
        prefs.getString("cfg_flip", "0.78")?.toDoubleOrNull() ?: 0.78,
        prefs.getString("cfg_exit", "0.20")?.toDoubleOrNull() ?: 0.20
    )

    @Synchronized
    fun saveConfig(c: SignalConfig) {
        prefs.edit()
            .putString("cfg_enter", "%.4f".format(Locale.US, c.enter))
            .putString("cfg_flip", "%.4f".format(Locale.US, c.flip))
            .putString("cfg_exit", "%.4f".format(Locale.US, c.exit))
            .apply()
    }

    fun notional(): Double = prefs.getString("paper_notional", "100000")?.toDoubleOrNull()?.coerceAtLeast(1000.0) ?: 100000.0
    fun stopPct(): Double = prefs.getString("stop_pct", "0.45")?.toDoubleOrNull()?.coerceIn(0.10, 3.0) ?: 0.45
    fun trailActivationPct(): Double = prefs.getString("trail_activation_pct", "0.45")?.toDoubleOrNull()?.coerceIn(0.10, 5.0) ?: 0.45
    fun trailDistancePct(): Double = prefs.getString("trail_distance_pct", "0.20")?.toDoubleOrNull()?.coerceIn(0.05, 2.0) ?: 0.20
    fun minHoldSeconds(): Long = prefs.getString("min_hold_seconds", "45")?.toLongOrNull()?.coerceIn(10, 600) ?: 45L

    fun saveRiskSettings(notional: String, stop: String, trailActivation: String, trailDistance: String, minHold: String) {
        prefs.edit()
            .putString("paper_notional", notional.trim())
            .putString("stop_pct", stop.trim())
            .putString("trail_activation_pct", trailActivation.trim())
            .putString("trail_distance_pct", trailDistance.trim())
            .putString("min_hold_seconds", minHold.trim())
            .apply()
    }

    fun accessToken(): String = secret.get("groww_access_token")
    fun apiKey(): String = secret.get("groww_api_key")
    fun apiSecret(): String = secret.get("groww_api_secret")
    fun saveAccessToken(v: String) { secret.put("groww_access_token", v.trim()); prefs.edit().remove("groww_validated_token_day").apply() }
    fun saveApiKey(v: String) { secret.put("groww_api_key", v.trim()) }
    fun saveApiSecret(v: String) { secret.put("groww_api_secret", v.trim()) }
    fun growwCredentialsConfigured(): Boolean = apiKey().isNotBlank() && apiSecret().isNotBlank()

    fun markGrowwValidated() { prefs.edit().putString("groww_validated_token_day", MarketClock.tokenDay()).putLong("groww_validated_ts", System.currentTimeMillis()).apply() }
    fun clearGrowwValidation() { prefs.edit().remove("groww_validated_token_day").remove("groww_validated_ts").apply() }
    fun growwValidated(): Boolean = accessToken().isNotBlank() && prefs.getString("groww_validated_token_day", "") == MarketClock.tokenDay()
    fun growwValidatedTs(): Long = prefs.getLong("groww_validated_ts", 0L)

    fun whitelistIp(): String = prefs.getString("whitelist_ip", "") ?: ""
    fun detectedIp(): String = prefs.getString("detected_ip", "") ?: ""
    fun saveWhitelistIp(ip: String) { prefs.edit().putString("whitelist_ip", ip.trim()).apply() }
    fun saveDetectedIp(ip: String) { prefs.edit().putString("detected_ip", ip.trim()).putLong("ip_detected_ts", System.currentTimeMillis()).apply() }
    fun staticIpVerified(): Boolean = whitelistIp().isNotBlank() && whitelistIp() == detectedIp()

    fun sourcePackage(): String = prefs.getString("source_package", "") ?: ""
    fun saveSourcePackage(v: String) { prefs.edit().putString("source_package", v.trim()).apply() }

    fun notificationAccessEnabled(): Boolean {
        val flat = Settings.Secure.getString(context.contentResolver, "enabled_notification_listeners") ?: return false
        return flat.split(":").any { it.startsWith(context.packageName + "/") || it.contains(context.packageName) }
    }

    fun listenerHeartbeatTs(): Long = prefs.getLong("listener_heartbeat_ts", 0L)
    fun markListenerHeartbeat() { prefs.edit().putLong("listener_heartbeat_ts", System.currentTimeMillis()).apply() }
    fun lastFeedTs(): Long = prefs.getLong("last_feed_ts", 0L)
    fun markFeed() { prefs.edit().putLong("last_feed_ts", System.currentTimeMillis()).apply() }

    private fun candidateToJson(c: CandidateState): JSONObject = JSONObject()
        .put("id", c.id).put("symbol", c.symbol).put("source", c.source).put("acceptedTs", c.acceptedTs)
        .put("status", c.status).put("lastLtp", c.lastLtp).put("lastUpdatedTs", c.lastUpdatedTs)
        .put("score", c.score).put("rvol", c.rvol).put("vwapPct", c.vwapPct).put("trend", c.trend)
        .put("paperSide", c.paperSide).put("entryPrice", c.entryPrice).put("entryTs", c.entryTs)
        .put("qty", c.qty).put("bestPrice", c.bestPrice).put("realisedPnl", c.realisedPnl)
        .put("rawNotification", c.rawNotification).put("notificationPackage", c.notificationPackage)

    private fun candidateFromJson(j: JSONObject): CandidateState = CandidateState(
        id = j.getString("id"), symbol = j.getString("symbol"), source = j.optString("source", "MULTYFI"),
        acceptedTs = j.getLong("acceptedTs"), status = j.optString("status", "ACTIVE"),
        lastLtp = j.optDouble("lastLtp", 0.0), lastUpdatedTs = j.optLong("lastUpdatedTs", 0L),
        score = j.optDouble("score", 0.0), rvol = j.optDouble("rvol", 1.0), vwapPct = j.optDouble("vwapPct", 0.0),
        trend = j.optString("trend", "WAITING"), paperSide = j.optString("paperSide", "FLAT"),
        entryPrice = j.optDouble("entryPrice", 0.0), entryTs = j.optLong("entryTs", 0L), qty = j.optInt("qty", 0),
        bestPrice = j.optDouble("bestPrice", 0.0), realisedPnl = j.optDouble("realisedPnl", 0.0),
        rawNotification = j.optString("rawNotification", ""), notificationPackage = j.optString("notificationPackage", "")
    )

    @Synchronized
    fun candidates(): List<CandidateState> {
        if (!candidatesFile.exists()) return emptyList()
        return runCatching {
            val a = JSONArray(candidatesFile.readText())
            (0 until a.length()).map { candidateFromJson(a.getJSONObject(it)) }
        }.getOrDefault(emptyList())
    }

    @Synchronized
    fun saveCandidate(c: CandidateState) {
        val list = candidates().toMutableList()
        val i = list.indexOfFirst { it.id == c.id }
        if (i >= 0) list[i] = c else list += c
        val a = JSONArray(); list.forEach { a.put(candidateToJson(it)) }
        candidatesFile.writeText(a.toString())
    }

    @Synchronized
    fun acceptCandidate(symbol: String, source: String, raw: String, pkg: String): CandidateState {
        val day = MarketClock.dayKey()
        candidates().firstOrNull { it.symbol == symbol && MarketClock.dayKey(it.acceptedTs) == day }?.let { return it }
        val c = CandidateState(
            id = "${day}_${symbol}_${UUID.randomUUID().toString().take(8)}",
            symbol = symbol,
            source = source,
            acceptedTs = System.currentTimeMillis(),
            rawNotification = raw.take(2000),
            notificationPackage = pkg
        )
        saveCandidate(c)
        logActivity("SYSTEM", "$symbol accepted", "$source candidate captured from Multyfi notification.")
        return c
    }

    fun todayCandidates(): List<CandidateState> = candidates().filter { MarketClock.dayKey(it.acceptedTs) == MarketClock.dayKey() }

    @Synchronized
    fun logTrade(e: TradeEvent) {
        val j = JSONObject()
            .put("ts", e.ts).put("candidateId", e.candidateId).put("symbol", e.symbol).put("side", e.side)
            .put("action", e.action).put("price", e.price).put("qty", e.qty).put("pnl", e.pnl)
            .put("reason", e.reason).put("score", e.score).put("rvol", e.rvol).put("vwapPct", e.vwapPct).put("mfePnl", e.mfePnl)
        tradesFile.appendText(j.toString() + "\n")
        if (e.action.equals("CLOSE", true)) {
            prefs.edit().putLong("evidence_version", evidenceVersion() + 1L).apply()
        }
    }

    fun allTrades(): List<TradeEvent> {
        if (!tradesFile.exists()) return emptyList()
        return tradesFile.readLines().mapNotNull { line -> runCatching {
            val j = JSONObject(line)
            TradeEvent(
                ts = j.getLong("ts"), candidateId = j.optString("candidateId", ""), symbol = j.getString("symbol"),
                side = j.getString("side"), action = j.getString("action"), price = j.optDouble("price", 0.0),
                qty = j.optInt("qty", 0), pnl = j.optDouble("pnl", 0.0), reason = j.optString("reason", ""),
                score = j.optDouble("score", 0.0), rvol = j.optDouble("rvol", 1.0), vwapPct = j.optDouble("vwapPct", 0.0),
                mfePnl = j.optDouble("mfePnl", 0.0)
            )
        }.getOrNull() }
    }

    fun todayTrades(): List<TradeEvent> = allTrades().filter { MarketClock.dayKey(it.ts) == MarketClock.dayKey() }

    @Synchronized
    fun logActivity(type: String, title: String, detail: String, severity: String = "INFO") {
        val j = JSONObject().put("ts", System.currentTimeMillis()).put("type", type).put("title", title).put("detail", detail.take(3000)).put("severity", severity)
        activityFile.appendText(j.toString() + "\n")
    }

    fun allActivity(): List<ActivityItem> {
        val system = if (!activityFile.exists()) emptyList() else activityFile.readLines().mapNotNull { line -> runCatching {
            val j = JSONObject(line)
            ActivityItem(j.getLong("ts"), j.optString("type", "SYSTEM"), j.optString("title", "Event"), j.optString("detail", ""), j.optString("severity", "INFO"))
        }.getOrNull() }
        val trades = allTrades().map { e ->
            val money = if (e.action.equals("CLOSE", true)) " • P&L ₹${"%.2f".format(Locale.US, e.pnl)}" else ""
            ActivityItem(e.ts, "TRADE", "${e.symbol} ${e.side} ${e.action}", "${e.reason}$money", if (e.pnl < 0) "WARN" else "INFO")
        }
        return (system + trades).sortedByDescending { it.ts }
    }

    fun todayActivity(): List<ActivityItem> = allActivity().filter { MarketClock.dayKey(it.ts) == MarketClock.dayKey() }

    private fun tickFile(candidateId: String): File = File(ticksDir, candidateId.replace(Regex("[^A-Za-z0-9_.-]"), "_") + ".jsonl")

    @Synchronized
    fun appendTick(candidateId: String, q: GrowwQuote): MarketTick {
        val t = MarketTick(System.currentTimeMillis(), q.symbol, q.lastPrice, q.volume, q.averagePrice, q.bidPrice, q.offerPrice)
        val j = JSONObject().put("ts", t.ts).put("symbol", t.symbol).put("price", t.price).put("volume", t.volume)
            .put("averagePrice", t.averagePrice).put("bidPrice", t.bidPrice).put("offerPrice", t.offerPrice)
        tickFile(candidateId).appendText(j.toString() + "\n")
        markFeed()
        return t
    }

    fun ticks(candidateId: String): List<MarketTick> {
        val f = tickFile(candidateId)
        if (!f.exists()) return emptyList()
        return f.readLines().mapNotNull { line -> runCatching {
            val j = JSONObject(line)
            MarketTick(j.getLong("ts"), j.getString("symbol"), j.getDouble("price"), j.optLong("volume", 0L),
                j.optDouble("averagePrice", 0.0), j.optDouble("bidPrice", 0.0), j.optDouble("offerPrice", 0.0))
        }.getOrNull() }
    }

    fun replaySessions(): List<Pair<String, List<MarketTick>>> = ticksDir.listFiles { f -> f.isFile && f.name.endsWith(".jsonl") }
        ?.map { f -> f.nameWithoutExtension to f.readLines().mapNotNull { line -> runCatching {
            val j = JSONObject(line)
            MarketTick(j.getLong("ts"), j.getString("symbol"), j.getDouble("price"), j.optLong("volume", 0L),
                j.optDouble("averagePrice", 0.0), j.optDouble("bidPrice", 0.0), j.optDouble("offerPrice", 0.0))
        }.getOrNull() } }
        ?.filter { it.second.isNotEmpty() }
        ?.sortedBy { it.second.first().ts }
        ?: emptyList()

    fun todayRawTickLines(): List<String> = ticksDir.listFiles { f -> f.isFile && f.name.startsWith(MarketClock.dayKey()) && f.name.endsWith(".jsonl") }
        ?.sortedBy { it.name }
        ?.flatMap { f -> listOf("# ${f.name}") + f.readLines() }
        ?: emptyList()

    fun evidenceVersion(): Long = prefs.getLong("evidence_version", 0L)
    fun lastLearningEvidenceVersion(): Long = prefs.getLong("last_learning_evidence_version", -1L)
    fun learningUpToDate(): Boolean = lastLearningEvidenceVersion() == evidenceVersion() && lastLearningTs() > 0L
    fun lastLearningTs(): Long = prefs.getLong("last_learning_ts", 0L)

    private fun metricsJson(m: LearningMetrics): JSONObject = JSONObject().put("trades", m.trades).put("wins", m.wins)
        .put("accuracy", m.accuracy).put("pnl", m.pnl).put("maxDrawdown", m.maxDrawdown).put("profitFactor", m.profitFactor)
    private fun configJson(c: SignalConfig): JSONObject = JSONObject().put("enter", c.enter).put("flip", c.flip).put("exit", c.exit)

    @Synchronized
    fun recordLearning(r: LearningResult) {
        val j = JSONObject().put("ts", r.ts).put("evaluated", r.evaluated).put("promoted", r.promoted).put("reason", r.reason)
            .put("sessionsUsed", r.sessionsUsed).put("trainSessions", r.trainSessions).put("validationSessions", r.validationSessions)
            .put("evidenceVersion", r.evidenceVersion).put("championBefore", configJson(r.championBefore)).put("challenger", configJson(r.challenger))
            .put("championAfter", configJson(r.championAfter)).put("challengerTrain", metricsJson(r.challengerTrain))
            .put("challengerValidation", metricsJson(r.challengerValidation)).put("championValidation", metricsJson(r.championValidation))
        learningFile.appendText(j.toString() + "\n")
        prefs.edit().putLong("last_learning_ts", r.ts).putLong("last_learning_evidence_version", r.evidenceVersion).apply()
        logActivity("LEARNING", if (r.promoted) "Challenger promoted" else if (r.evaluated) "Champion kept" else "Learning evidence incomplete", r.reason)
    }

    private fun configFrom(j: JSONObject): SignalConfig = SignalConfig(j.optDouble("enter", 0.68), j.optDouble("flip", 0.78), j.optDouble("exit", 0.20))
    private fun metricsFrom(j: JSONObject?): LearningMetrics = if (j == null) LearningMetrics() else LearningMetrics(
        j.optInt("trades", 0), j.optInt("wins", 0), j.optDouble("accuracy", 0.0), j.optDouble("pnl", 0.0),
        j.optDouble("maxDrawdown", 0.0), j.optDouble("profitFactor", 0.0)
    )

    fun lastLearning(): LearningResult? {
        val line = learningFile.takeIf { it.exists() }?.readLines()?.lastOrNull() ?: return null
        return runCatching {
            val j = JSONObject(line)
            LearningResult(
                ts = j.getLong("ts"), evaluated = j.optBoolean("evaluated", false), promoted = j.optBoolean("promoted", false),
                reason = j.optString("reason", ""), sessionsUsed = j.optInt("sessionsUsed", 0), trainSessions = j.optInt("trainSessions", 0),
                validationSessions = j.optInt("validationSessions", 0), evidenceVersion = j.optLong("evidenceVersion", 0L),
                championBefore = configFrom(j.getJSONObject("championBefore")), challenger = configFrom(j.getJSONObject("challenger")),
                championAfter = configFrom(j.getJSONObject("championAfter")), challengerTrain = metricsFrom(j.optJSONObject("challengerTrain")),
                challengerValidation = metricsFrom(j.optJSONObject("challengerValidation")), championValidation = metricsFrom(j.optJSONObject("championValidation"))
            )
        }.getOrNull()
    }

    fun learningHistoryLines(): List<String> = learningFile.takeIf { it.exists() }?.readLines() ?: emptyList()

    fun dayMetrics(): LearningMetrics {
        val closed = todayTrades().filter { it.action.equals("CLOSE", true) }
        if (closed.isEmpty()) return LearningMetrics()
        val wins = closed.count { it.pnl > 0.0 }
        var running = 0.0; var peak = 0.0; var dd = 0.0; var gp = 0.0; var gl = 0.0
        closed.sortedBy { it.ts }.forEach { e ->
            running += e.pnl; if (running > peak) peak = running; dd = maxOf(dd, peak - running)
            if (e.pnl > 0) gp += e.pnl else gl += -e.pnl
        }
        return LearningMetrics(closed.size, wins, wins.toDouble() / closed.size.toDouble(), closed.sumOf { it.pnl }, dd,
            if (gl <= 0.0) if (gp > 0) 99.0 else 0.0 else gp / gl)
    }

    fun captureEfficiency(): Double {
        val closed = todayTrades().filter { it.action.equals("CLOSE", true) && it.mfePnl > 0.0 }
        if (closed.isEmpty()) return 0.0
        val captured = closed.sumOf { maxOf(0.0, it.pnl) }
        val possible = closed.sumOf { it.mfePnl }
        return if (possible <= 0.0) 0.0 else (captured / possible).coerceIn(0.0, 1.0)
    }

    fun diagnosticsSummary(): String = "${sdf.format(Date())} • evidence=${evidenceVersion()} • candidates=${todayCandidates().size} • trades=${todayTrades().size}"
}
