package com.multyfi.dailylearner

import kotlin.math.abs
import kotlin.math.max

class LearningEngine {
    private fun scoreEvent(e: TradeEvent, c: SignalConfig): Double {
        val direction = if (e.side.equals("LONG", true)) 1.0 else -1.0
        val quality = direction * e.score + 0.08 * (e.rvol - 1.0) + 0.20 * direction * e.vwapPct
        val entryPenalty = abs(c.enter - abs(quality)) * 20.0
        val flipPenalty = if (e.reason.contains("flip", true) || e.reason.contains("reversal", true)) abs(c.flip - abs(quality)) * 15.0 else 0.0
        val exitPenalty = if (e.action.equals("CLOSE", true)) abs(c.exit - abs(quality)) * 8.0 else 0.0
        return e.pnl - entryPenalty - flipPenalty - exitPenalty
    }

    private fun evaluate(events: List<TradeEvent>, c: SignalConfig): Pair<Double, Double> {
        val closed = events.filter { it.action.equals("CLOSE", true) }
        if (closed.isEmpty()) return 0.0 to 0.0
        val wins = closed.count { it.pnl > 0 }
        val acc = wins.toDouble() / closed.size.toDouble()
        val pnl = closed.sumOf { scoreEvent(it, c) }
        return acc to pnl
    }

    fun learn(allEvents: List<TradeEvent>, champion: SignalConfig): LearningResult {
        val closed = allEvents.filter { it.action.equals("CLOSE", true) }
        if (closed.size < 6) {
            return LearningResult(0.0, 0.0, closed.sumOf { it.pnl }, champion, champion, champion, false,
                "Not enough completed trades for guarded learning (need at least 6).", closed.map { it.ts / 86_400_000L }.distinct().size)
        }

        val split = max(1, (closed.size * 0.75).toInt())
        val train = closed.take(split)
        val validation = closed.drop(split).ifEmpty { closed.takeLast(1) }

        val candidates = mutableListOf<SignalConfig>()
        for (de in listOf(-0.08, -0.04, 0.0, 0.04, 0.08))
            for (df in listOf(-0.08, -0.04, 0.0, 0.04, 0.08))
                for (dx in listOf(-0.04, 0.0, 0.04))
                    candidates += SignalConfig(
                        (champion.enter + de).coerceIn(0.35, 0.90),
                        (champion.flip + df).coerceIn(0.45, 0.95),
                        (champion.exit + dx).coerceIn(0.05, 0.45)
                    )

        val challenger = candidates.maxBy { evaluate(train, it).second }
        val (trainAcc, _) = evaluate(train, challenger)
        val (valAcc, valPnl) = evaluate(validation, challenger)
        val (champValAcc, champValPnl) = evaluate(validation, champion)

        val promoted = valAcc >= champValAcc + 0.03 && valPnl > champValPnl && valAcc >= 0.45
        val reason = if (promoted) {
            "PROMOTED: challenger improved validation accuracy by ${(valAcc - champValAcc) * 100.0}% and validation replay score by ${valPnl - champValPnl}."
        } else {
            buildString {
                append("KEPT CHAMPION: ")
                if (valAcc < 0.45) append("challenger validation accuracy below 45%; ")
                if (valAcc < champValAcc + 0.03) append("validation accuracy did not beat champion by at least 3pp; ")
                if (valPnl <= champValPnl) append("validation replay score did not beat champion; ")
            }.trim()
        }
        val after = if (promoted) challenger else champion
        return LearningResult(trainAcc, valAcc, valPnl, champion, challenger, after, promoted, reason,
            closed.map { it.ts / 86_400_000L }.distinct().size)
    }
}
