package com.multyfi.dailylearner

import android.content.Context
import org.json.JSONObject
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

class AppRepository(private val context: Context) {
    private val prefs = context.getSharedPreferences("learning", Context.MODE_PRIVATE)
    private val eventsFile = File(context.filesDir, "events.jsonl")
    private val learningFile = File(context.filesDir, "learning_history.jsonl")
    private val dayFmt = SimpleDateFormat("yyyy-MM-dd", Locale.US)

    fun currentConfig(): SignalConfig = SignalConfig(
        prefs.getFloat("enter", 0.68f).toDouble(),
        prefs.getFloat("flip", 0.78f).toDouble(),
        prefs.getFloat("exit", 0.20f).toDouble()
    )

    fun saveConfig(c: SignalConfig) {
        prefs.edit()
            .putFloat("enter", c.enter.toFloat())
            .putFloat("flip", c.flip.toFloat())
            .putFloat("exit", c.exit.toFloat())
            .apply()
    }

    fun logEvent(e: TradeEvent) {
        val j = JSONObject()
            .put("ts", e.ts)
            .put("symbol", e.symbol)
            .put("side", e.side)
            .put("action", e.action)
            .put("price", e.price)
            .put("pnl", e.pnl)
            .put("reason", e.reason)
            .put("score", e.score)
            .put("rvol", e.rvol)
            .put("vwapPct", e.vwapPct)
        eventsFile.appendText(j.toString() + "\n")
    }

    fun allEvents(): List<TradeEvent> {
        if (!eventsFile.exists()) return emptyList()
        return eventsFile.readLines().mapNotNull { line ->
            runCatching {
                val j = JSONObject(line)
                TradeEvent(
                    j.getLong("ts"), j.getString("symbol"), j.getString("side"),
                    j.getString("action"), j.getDouble("price"), j.optDouble("pnl", 0.0),
                    j.optString("reason", ""), j.optDouble("score", 0.0),
                    j.optDouble("rvol", 1.0), j.optDouble("vwapPct", 0.0)
                )
            }.getOrNull()
        }
    }

    fun todayEvents(now: Long = System.currentTimeMillis()): List<TradeEvent> {
        val d = dayFmt.format(Date(now))
        return allEvents().filter { dayFmt.format(Date(it.ts)) == d }
    }

    fun recordLearning(result: LearningResult) {
        val j = JSONObject()
            .put("ts", System.currentTimeMillis())
            .put("trainAccuracy", result.trainAccuracy)
            .put("validationAccuracy", result.validationAccuracy)
            .put("replayPnl", result.replayPnl)
            .put("promoted", result.promoted)
            .put("reason", result.reason)
            .put("sessionsUsed", result.sessionsUsed)
            .put("championBefore", JSONObject().put("enter", result.championBefore.enter).put("flip", result.championBefore.flip).put("exit", result.championBefore.exit))
            .put("challenger", JSONObject().put("enter", result.challenger.enter).put("flip", result.challenger.flip).put("exit", result.challenger.exit))
            .put("championAfter", JSONObject().put("enter", result.championAfter.enter).put("flip", result.championAfter.flip).put("exit", result.championAfter.exit))
        learningFile.appendText(j.toString() + "\n")
        prefs.edit().putLong("last_learning_ts", System.currentTimeMillis()).apply()
    }

    fun lastLearningLine(): String? = learningFile.takeIf { it.exists() }?.readLines()?.lastOrNull()
    fun lastLearningTs(): Long = prefs.getLong("last_learning_ts", 0L)
    fun dayString(ts: Long): String = dayFmt.format(Date(ts))
}
