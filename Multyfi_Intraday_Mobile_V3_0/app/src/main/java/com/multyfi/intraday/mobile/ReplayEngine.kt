package com.multyfi.intraday.mobile

import kotlin.math.floor
import kotlin.math.max

class ReplayEngine {
    private data class SimTrade(val pnl: Double)

    fun learn(repo: AppRepository): LearningResult {
        val now = System.currentTimeMillis()
        val champion = repo.currentConfig()
        val sessions = repo.replaySessions()
            .mapNotNull { (id, ticks) -> if (ticks.size >= 24) id to SignalMath.series(ticks) else null }
            .sortedBy { it.second.firstOrNull()?.ts ?: Long.MAX_VALUE }

        if (sessions.size < 6) {
            return LearningResult(
                ts = now,
                evaluated = false,
                promoted = false,
                reason = "Collecting evidence: ${sessions.size}/6 completed replay sessions. The Champion is unchanged.",
                sessionsUsed = sessions.size,
                trainSessions = 0,
                validationSessions = 0,
                evidenceVersion = repo.evidenceVersion(),
                championBefore = champion,
                challenger = champion,
                championAfter = champion,
                challengerTrain = LearningMetrics(),
                challengerValidation = LearningMetrics(),
                championValidation = LearningMetrics()
            )
        }

        val split = max(4, (sessions.size * 0.75).toInt()).coerceAtMost(sessions.size - 2)
        val train = sessions.take(split)
        val validation = sessions.drop(split)

        val candidates = mutableListOf<SignalConfig>()
        for (de in listOf(-0.06, -0.03, 0.0, 0.03, 0.06)) {
            for (df in listOf(-0.06, -0.03, 0.0, 0.03, 0.06)) {
                for (dx in listOf(-0.04, 0.0, 0.04)) {
                    candidates += SignalConfig(
                        (champion.enter + de).coerceIn(0.42, 0.90),
                        (champion.flip + df).coerceIn(0.50, 0.95),
                        (champion.exit + dx).coerceIn(0.08, 0.40)
                    )
                }
            }
        }

        fun objective(m: LearningMetrics): Double = m.pnl - 0.50 * m.maxDrawdown + 100.0 * m.accuracy + 35.0 * m.profitFactor.coerceAtMost(3.0)
        val challenger = candidates.maxBy { objective(metrics(train, it, repo)) }
        val trainM = metrics(train, challenger, repo)
        val valM = metrics(validation, challenger, repo)
        val champVal = metrics(validation, champion, repo)

        val gates = mutableListOf<String>()
        if (valM.accuracy < 0.45) gates += "validation accuracy ${pct(valM.accuracy)} is below 45%"
        if (valM.accuracy < champVal.accuracy + 0.03) gates += "validation accuracy did not beat Champion by 3 percentage points"
        if (valM.pnl <= champVal.pnl) gates += "validation P&L did not beat Champion"
        if (champVal.maxDrawdown > 0.0 && valM.maxDrawdown > champVal.maxDrawdown * 1.05) gates += "validation drawdown is more than 5% worse than Champion"
        if (valM.trades < 4) gates += "validation produced fewer than 4 closed legs"

        val promoted = gates.isEmpty()
        val reason = if (promoted) {
            "PROMOTED: Challenger cleared validation gates — accuracy ${pct(valM.accuracy)} vs ${pct(champVal.accuracy)}, P&L ₹${money(valM.pnl)} vs ₹${money(champVal.pnl)}, drawdown ₹${money(valM.maxDrawdown)}."
        } else {
            "KEPT CHAMPION: " + gates.joinToString("; ") + "."
        }
        val after = if (promoted) challenger else champion
        return LearningResult(
            ts = now,
            evaluated = true,
            promoted = promoted,
            reason = reason,
            sessionsUsed = sessions.size,
            trainSessions = train.size,
            validationSessions = validation.size,
            evidenceVersion = repo.evidenceVersion(),
            championBefore = champion,
            challenger = challenger,
            championAfter = after,
            challengerTrain = trainM,
            challengerValidation = valM,
            championValidation = champVal
        )
    }

    private fun metrics(sessions: List<Pair<String, List<SignalFeature>>>, cfg: SignalConfig, repo: AppRepository): LearningMetrics {
        val trades = sessions.flatMap { simulate(it.second, cfg, repo) }
        if (trades.isEmpty()) return LearningMetrics()
        val wins = trades.count { it.pnl > 0.0 }
        var running = 0.0
        var peak = 0.0
        var dd = 0.0
        var gp = 0.0
        var gl = 0.0
        trades.forEach { t ->
            running += t.pnl
            peak = max(peak, running)
            dd = max(dd, peak - running)
            if (t.pnl > 0.0) gp += t.pnl else gl += -t.pnl
        }
        val pf = if (gl <= 0.0) if (gp > 0.0) 9.99 else 0.0 else gp / gl
        return LearningMetrics(trades.size, wins, wins.toDouble() / trades.size.toDouble(), trades.sumOf { it.pnl }, dd, pf)
    }

    private fun simulate(points: List<SignalFeature>, cfg: SignalConfig, repo: AppRepository): List<SimTrade> {
        if (points.size < 2) return emptyList()
        val out = mutableListOf<SimTrade>()
        var side = "FLAT"
        var entry = 0.0
        var entryTs = 0L
        var qty = 0
        var best = 0.0

        fun signedReturn(price: Double): Double {
            val raw = if (entry > 0.0) (price / entry - 1.0) * 100.0 else 0.0
            return if (side == "LONG") raw else -raw
        }
        fun close(price: Double) {
            if (side == "FLAT") return
            val p = if (side == "LONG") (price - entry) * qty else (entry - price) * qty
            out += SimTrade(p)
            side = "FLAT"; entry = 0.0; entryTs = 0L; qty = 0; best = 0.0
        }
        fun open(s: String, p: SignalFeature) {
            side = s; entry = p.price; entryTs = p.ts; qty = max(1, floor(repo.notional() / p.price).toInt()); best = p.price
        }

        points.forEachIndexed { i, p ->
            if (side == "FLAT") {
                if (p.score >= cfg.enter) open("LONG", p) else if (p.score <= -cfg.enter) open("SHORT", p)
            } else {
                best = if (side == "LONG") max(best, p.price) else minOf(best, p.price)
                val currentRet = signedReturn(p.price)
                val bestRet = signedReturn(best)
                val held = (p.ts - entryTs) / 1000L
                val reverse = held >= repo.minHoldSeconds() && ((side == "LONG" && p.score <= -cfg.flip) || (side == "SHORT" && p.score >= cfg.flip))
                val fade = held >= repo.minHoldSeconds() && kotlin.math.abs(p.score) <= cfg.exit
                val stop = currentRet <= -repo.stopPct()
                val trail = bestRet >= repo.trailActivationPct() && (bestRet - currentRet) >= repo.trailDistancePct()
                if (stop || trail || reverse || fade || i == points.lastIndex) {
                    val old = side
                    close(p.price)
                    if (reverse && i != points.lastIndex) open(if (old == "LONG") "SHORT" else "LONG", p)
                }
            }
        }
        if (side != "FLAT") close(points.last().price)
        return out
    }

    private fun pct(v: Double) = "%.1f%%".format(v * 100.0)
    private fun money(v: Double) = "%.0f".format(v)
}
