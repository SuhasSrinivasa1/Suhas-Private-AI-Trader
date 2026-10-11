package com.multyfi.intraday.mobile

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.Locale

class CandidateSanitizer(private val context: Context) {
    private val candidatesFile = File(context.filesDir, "candidates.json")
    private val tradesFile = File(context.filesDir, "trade_events.jsonl")
    private val activityFile = File(context.filesDir, "activity.jsonl")
    private val learningFile = File(context.filesDir, "learning_history.jsonl")
    private val ticksDir = File(context.filesDir, "ticks")
    private val prefs = context.getSharedPreferences("multyfi_v3", Context.MODE_PRIVATE)

    data class Result(
        val removedCandidates: Int,
        val removedTrades: Int,
        val removedTicks: Int
    )

    @Synchronized
    fun purgeToday(validSymbols: Set<String>): Result {
        if (validSymbols.isEmpty() || !candidatesFile.exists()) return Result(0, 0, 0)
        val today = MarketClock.dayKey()
        val all = runCatching {
            val a = JSONArray(candidatesFile.readText())
            (0 until a.length()).map { a.getJSONObject(it) }
        }.getOrDefault(emptyList())
        if (all.isEmpty()) return Result(0, 0, 0)

        val invalid = all.filter { j ->
            val ts = j.optLong("acceptedTs", 0L)
            val symbol = j.optString("symbol", "").uppercase(Locale.US)
            ts > 0L && MarketClock.dayKey(ts) == today && symbol !in validSymbols
        }
        if (invalid.isEmpty()) return Result(0, 0, 0)

        val invalidIds = invalid.mapNotNull { it.optString("id", "").takeIf(String::isNotBlank) }.toSet()
        val invalidSymbols = invalid.map { it.optString("symbol", "").uppercase(Locale.US) }.toSet()
        val keep = all.filterNot { it.optString("id", "") in invalidIds }
        val out = JSONArray()
        keep.forEach { out.put(it) }
        candidatesFile.writeText(out.toString())

        var removedTicks = 0
        invalidIds.forEach { id ->
            val f = File(ticksDir, id.replace(Regex("[^A-Za-z0-9_.-]"), "_") + ".jsonl")
            if (f.exists() && f.delete()) removedTicks++
        }

        var removedTrades = 0
        if (tradesFile.exists()) {
            val keptTradeLines = ArrayList<String>()
            tradesFile.readLines().forEach { line ->
                val remove = runCatching {
                    JSONObject(line).optString("candidateId", "") in invalidIds
                }.getOrDefault(false)
                if (remove) removedTrades++ else if (line.isNotBlank()) keptTradeLines += line
            }
            tradesFile.writeText(if (keptTradeLines.isEmpty()) "" else keptTradeLines.joinToString("\n", postfix = "\n"))
        }

        if (activityFile.exists()) {
            val keptActivity = activityFile.readLines().filter { line ->
                runCatching {
                    val j = JSONObject(line)
                    val ts = j.optLong("ts", 0L)
                    if (ts <= 0L || MarketClock.dayKey(ts) != today) return@runCatching true
                    val title = j.optString("title", "")
                    invalidSymbols.none { symbol ->
                        title.equals("$symbol accepted", true) ||
                            title.equals("Market data error • $symbol", true)
                    }
                }.getOrDefault(true)
            }
            activityFile.writeText(if (keptActivity.isEmpty()) "" else keptActivity.joinToString("\n", postfix = "\n"))
        }

        if (removedTrades > 0 || removedTicks > 0) {
            if (learningFile.exists()) {
                val keptLearning = learningFile.readLines().filter { line ->
                    runCatching {
                        val ts = JSONObject(line).optLong("ts", 0L)
                        ts <= 0L || MarketClock.dayKey(ts) != today
                    }.getOrDefault(true)
                }
                learningFile.writeText(if (keptLearning.isEmpty()) "" else keptLearning.joinToString("\n", postfix = "\n"))
            }
            prefs.edit()
                .remove("last_learning_ts")
                .remove("last_learning_evidence_version")
                .apply()
        }

        return Result(invalid.size, removedTrades, removedTicks)
    }
}
