from pathlib import Path

base = Path('Multyfi_Intraday_Mobile_V3_0')
src = base / 'app/src/main/java/com/multyfi/intraday/mobile'

# V3.0.10 builds on the verified V3.0.9 feed-resilience transformation.
p = base / 'app/build.gradle.kts'
s = p.read_text()
if 'versionCode = 309' not in s or 'versionName = "3.0.9"' not in s:
    raise SystemExit('Expected transformed V3.0.9 build config was not found')
s = s.replace('versionCode = 309', 'versionCode = 310', 1)
s = s.replace('versionName = "3.0.9"', 'versionName = "3.0.10"', 1)
p.write_text(s)

# Persist entry-confirmation/cooldown state in each candidate and carry Groww exchange time.
p = src / 'Models.kt'
s = p.read_text()
needle = '    val riskMinHoldSeconds: Long = 0L,\n    val rawNotification: String = "",\n'
repl = '''    val riskMinHoldSeconds: Long = 0L,\n    val lastExitTs: Long = 0L,\n    val entryConfirmSide: String = "",\n    val entryConfirmCount: Int = 0,\n    val entryConfirmStartTs: Long = 0L,\n    val rawNotification: String = "",\n'''
if needle not in s:
    raise SystemExit('CandidateState V3.0.7 risk hook not found')
s = s.replace(needle, repl, 1)
needle = '    val offerPrice: Double,\n    val rawStatus: String\n)\n'
repl = '''    val offerPrice: Double,\n    val rawStatus: String,\n    val lastTradeTime: Long = 0L\n)\n'''
if needle not in s:
    raise SystemExit('GrowwQuote model hook not found')
s = s.replace(needle, repl, 1)
p.write_text(s)

# Parse Groww exchange last_trade_time. Keep compatibility if the field is absent.
p = src / 'GrowwClient.kt'
s = p.read_text()
needle = '            val p = root.getJSONObject("payload")\n            GrowwQuote(\n'
repl = '''            val p = root.getJSONObject("payload")\n            val rawTradeTime = p.optLong("last_trade_time", p.optLong("last_trade_timestamp", 0L))\n            val tradeTime = when {\n                rawTradeTime in 1_000_000_000L..9_999_999_999L -> rawTradeTime * 1000L\n                rawTradeTime > 0L -> rawTradeTime\n                else -> 0L\n            }\n            GrowwQuote(\n'''
if needle not in s:
    raise SystemExit('Groww quote payload hook not found')
s = s.replace(needle, repl, 1)
needle = '                offerPrice = p.optDouble("offer_price", 0.0),\n                rawStatus = root.optString("status", "")\n'
repl = '''                offerPrice = p.optDouble("offer_price", 0.0),\n                rawStatus = root.optString("status", ""),\n                lastTradeTime = tradeTime\n'''
if needle not in s:
    raise SystemExit('Groww quote constructor hook not found')
s = s.replace(needle, repl, 1)
p.write_text(s)

# Candidate persistence + exchange-timestamped raw ticks.
p = src / 'AppRepository.kt'
s = p.read_text()
needle = '        .put("riskTrailDistancePct", c.riskTrailDistancePct).put("riskMinHoldSeconds", c.riskMinHoldSeconds)\n        .put("rawNotification", c.rawNotification).put("notificationPackage", c.notificationPackage)\n'
repl = '''        .put("riskTrailDistancePct", c.riskTrailDistancePct).put("riskMinHoldSeconds", c.riskMinHoldSeconds)\n        .put("lastExitTs", c.lastExitTs).put("entryConfirmSide", c.entryConfirmSide)\n        .put("entryConfirmCount", c.entryConfirmCount).put("entryConfirmStartTs", c.entryConfirmStartTs)\n        .put("rawNotification", c.rawNotification).put("notificationPackage", c.notificationPackage)\n'''
if needle not in s:
    raise SystemExit('Candidate serialization risk hook not found')
s = s.replace(needle, repl, 1)
needle = '        riskMinHoldSeconds = j.optLong("riskMinHoldSeconds", 0L),\n        rawNotification = j.optString("rawNotification", ""), notificationPackage = j.optString("notificationPackage", "")\n'
repl = '''        riskMinHoldSeconds = j.optLong("riskMinHoldSeconds", 0L),\n        lastExitTs = j.optLong("lastExitTs", 0L),\n        entryConfirmSide = j.optString("entryConfirmSide", ""),\n        entryConfirmCount = j.optInt("entryConfirmCount", 0),\n        entryConfirmStartTs = j.optLong("entryConfirmStartTs", 0L),\n        rawNotification = j.optString("rawNotification", ""), notificationPackage = j.optString("notificationPackage", "")\n'''
if needle not in s:
    raise SystemExit('Candidate deserialization risk hook not found')
s = s.replace(needle, repl, 1)
needle = '''    fun appendTick(candidateId: String, q: GrowwQuote): MarketTick {\n        val t = MarketTick(System.currentTimeMillis(), q.symbol, q.lastPrice, q.volume, q.averagePrice, q.bidPrice, q.offerPrice)\n        val j = JSONObject().put("ts", t.ts).put("symbol", t.symbol).put("price", t.price).put("volume", t.volume)\n            .put("averagePrice", t.averagePrice).put("bidPrice", t.bidPrice).put("offerPrice", t.offerPrice)\n        tickFile(candidateId).appendText(j.toString() + "\\n")\n        markFeed()\n        return t\n    }\n'''
repl = '''    fun appendTick(candidateId: String, q: GrowwQuote): MarketTick {\n        val receivedTs = System.currentTimeMillis()\n        val exchangeTs = if (q.lastTradeTime > 0L) q.lastTradeTime else receivedTs\n        val t = MarketTick(exchangeTs, q.symbol, q.lastPrice, q.volume, q.averagePrice, q.bidPrice, q.offerPrice)\n        val j = JSONObject().put("ts", t.ts).put("receivedTs", receivedTs).put("symbol", t.symbol).put("price", t.price).put("volume", t.volume)\n            .put("averagePrice", t.averagePrice).put("bidPrice", t.bidPrice).put("offerPrice", t.offerPrice)\n        tickFile(candidateId).appendText(j.toString() + "\\n")\n        markFeed()\n        return t\n    }\n'''
if needle not in s:
    raise SystemExit('appendTick hook not found')
s = s.replace(needle, repl, 1)
p.write_text(s)

# Central market-data quality filter used both live and in replay.
(src / 'MarketDataGuard.kt').write_text(r'''package com.multyfi.intraday.mobile

data class QuoteQuality(
    val accept: Boolean,
    val reason: String,
    val exchangeTs: Long
)

object MarketDataGuard {
    const val MAX_TRADE_AGE_MS = 30_000L
    private const val FUTURE_TOLERANCE_MS = 5_000L

    fun evaluate(previousRaw: List<MarketTick>, quote: GrowwQuote, nowMs: Long = System.currentTimeMillis()): QuoteQuality {
        if (quote.lastPrice <= 0.0) return QuoteQuality(false, "INVALID_PRICE", 0L)
        val exchangeTs = if (quote.lastTradeTime > 0L) quote.lastTradeTime else nowMs
        if (quote.lastTradeTime > 0L) {
            if (exchangeTs > nowMs + FUTURE_TOLERANCE_MS) return QuoteQuality(false, "FUTURE_TRADE_TIME", exchangeTs)
            if (nowMs - exchangeTs > MAX_TRADE_AGE_MS) return QuoteQuality(false, "STALE_TRADE_TIME", exchangeTs)
        }

        val previous = sanitizeTicks(previousRaw).lastOrNull()
        if (previous != null) {
            if (exchangeTs <= previous.ts) return QuoteQuality(false, "DUPLICATE_OR_OUT_OF_ORDER", exchangeTs)
            if (previous.volume > 0L && quote.volume > 0L && quote.volume < previous.volume) {
                return QuoteQuality(false, "VOLUME_REGRESSION", exchangeTs)
            }
        }
        return QuoteQuality(true, "OK", exchangeTs)
    }

    fun sanitizeTicks(raw: List<MarketTick>): List<MarketTick> {
        if (raw.isEmpty()) return emptyList()
        val out = ArrayList<MarketTick>(raw.size)
        var lastTs = Long.MIN_VALUE
        var lastVolume = 0L
        raw.forEach { t ->
            if (t.price <= 0.0 || t.ts <= lastTs) return@forEach
            if (lastVolume > 0L && t.volume > 0L && t.volume < lastVolume) return@forEach
            out += t
            lastTs = t.ts
            if (t.volume > 0L) lastVolume = t.volume
        }
        return out
    }
}
''')

# Add market-integrity filtering to the V3.0.9 resilient quote loop.
p = src / 'MultyfiNotificationService.kt'
s = p.read_text()
old = r'''            runCatching {
                val q = GrowwClient.quote(token, c.symbol)
                repo.appendTick(c.id, q)
                noteQuoteSuccess()

                val ticks = repo.ticks(c.id).takeLast(180)
                val gateUntil = maxOf(entryResumeAfterMs, repo.feedEntryResumeTs())
                val blockFreshEntry = feedDegraded || repo.feedDegraded() || System.currentTimeMillis() < gateUntil
                val updated = if (blockFreshEntry && c.paperSide == "FLAT") {
                    val f = SignalMath.latest(ticks)
                    c.copy(
                        lastLtp = f.price,
                        lastUpdatedTs = f.ts,
                        score = f.score,
                        rvol = f.rvol,
                        vwapPct = f.vwapPct,
                        trend = f.trend
                    )
                } else {
                    PaperEngine.onQuote(repo, c, ticks)
                }
                LiveTradeEngine.sync(repo, c, updated)
                repo.saveCandidate(updated)
            }.onFailure { e ->
                noteQuoteFailure(c.symbol, e)
            }
'''
new = r'''            runCatching {
                val q = GrowwClient.quote(token, c.symbol)
                val before = repo.ticks(c.id).takeLast(180)
                val quality = MarketDataGuard.evaluate(before, q)
                if (!quality.accept) {
                    val feedAge = System.currentTimeMillis() - repo.lastFeedTs()
                    when (quality.reason) {
                        "DUPLICATE_OR_OUT_OF_ORDER" -> {
                            if (feedAge > 35_000L) {
                                noteQuoteFailure(c.symbol, IllegalStateException("data quality: stale duplicate/out-of-order Groww quote"))
                            }
                        }
                        else -> noteQuoteFailure(c.symbol, IllegalStateException("data quality: ${quality.reason}"))
                    }
                    return@runCatching
                }

                val appended = repo.appendTick(c.id, q)
                noteQuoteSuccess()
                val ticks = (MarketDataGuard.sanitizeTicks(before) + appended).takeLast(180)
                val gateUntil = maxOf(entryResumeAfterMs, repo.feedEntryResumeTs())
                val blockFreshEntry = feedDegraded || repo.feedDegraded() || System.currentTimeMillis() < gateUntil
                val updated = if (blockFreshEntry && c.paperSide == "FLAT") {
                    val f = SignalMath.latest(ticks)
                    c.copy(
                        lastLtp = f.price,
                        lastUpdatedTs = f.ts,
                        score = f.score,
                        rvol = f.rvol,
                        vwapPct = f.vwapPct,
                        trend = f.trend,
                        entryConfirmSide = "",
                        entryConfirmCount = 0,
                        entryConfirmStartTs = 0L
                    )
                } else {
                    PaperEngine.onQuote(repo, c, ticks)
                }
                LiveTradeEngine.sync(repo, c, updated)
                repo.saveCandidate(updated)
            }.onFailure { e ->
                noteQuoteFailure(c.symbol, e)
            }
'''
if old not in s:
    raise SystemExit('V3.0.9 safePoll quote block not found')
s = s.replace(old, new, 1)
needle = '            "unable to resolve host" in m || "no address associated" in m || "unknownhost" in m -> "DNS"\n'
repl = '            "data quality" in m || "stale trade" in m || "volume regression" in m -> "DATA QUALITY"\n' + needle
if needle not in s:
    raise SystemExit('feed error classifier hook not found')
s = s.replace(needle, repl, 1)
needle = '        "AUTH" -> 30_000L\n'
repl = needle + '        "DATA QUALITY" -> when { streak >= 5 -> 8_000L; streak >= 3 -> 3_000L; else -> 1_000L }\n'
if needle not in s:
    raise SystemExit('retry delay hook not found')
s = s.replace(needle, repl, 1)
p.write_text(s)

# Replace live paper engine with exchange-time integrity + confirmation/cooldown anti-churn.
(src / 'PaperEngine.kt').write_text(r'''package com.multyfi.intraday.mobile

import kotlin.math.floor
import kotlin.math.max

object PaperEngine {
    private const val ENTRY_CONFIRMATIONS = 3
    private const val ENTRY_CONFIRM_MIN_SPAN_MS = 3_000L
    private const val REENTRY_COOLDOWN_MS = 90_000L

    private fun sideReturnPct(side: String, entry: Double, price: Double): Double {
        if (entry <= 0.0) return 0.0
        val raw = (price / entry - 1.0) * 100.0
        return if (side == "LONG") raw else -raw
    }

    private fun pnl(side: String, entry: Double, price: Double, qty: Int): Double =
        if (side == "LONG") (price - entry) * qty else (entry - price) * qty

    private fun clearPending(c: CandidateState): CandidateState =
        if (c.entryConfirmCount == 0 && c.entryConfirmSide.isBlank() && c.entryConfirmStartTs == 0L) c
        else c.copy(entryConfirmSide = "", entryConfirmCount = 0, entryConfirmStartTs = 0L)

    fun onQuote(repo: AppRepository, c0: CandidateState, ticksRaw: List<MarketTick>): CandidateState {
        val ticks = MarketDataGuard.sanitizeTicks(ticksRaw)
        if (ticks.isEmpty()) return c0
        val f = SignalMath.latest(ticks)
        val continuousFeed = SignalMath.hasRecentContinuity(ticks)
        var c = c0.copy(lastLtp = f.price, lastUpdatedTs = f.ts, score = f.score, rvol = f.rvol, vwapPct = f.vwapPct, trend = f.trend)

        if (MarketClock.shouldForceFlat()) {
            if (c.paperSide != "FLAT") c = close(repo, c, f, "15:15 IST force-flat")
            return clearPending(c).copy(status = "SESSION_LOCKED")
        }

        if (c.paperSide == "FLAT") {
            if (!MarketClock.canOpenNewPaperRisk() || !continuousFeed) return clearPending(c)
            if (c.lastExitTs > 0L && f.ts - c.lastExitTs < REENTRY_COOLDOWN_MS) return clearPending(c)

            val cfg = repo.currentConfig()
            val wanted = when {
                f.score >= cfg.enter -> "LONG"
                f.score <= -cfg.enter -> "SHORT"
                else -> ""
            }
            if (wanted.isBlank()) return clearPending(c)

            val same = c.entryConfirmSide == wanted && c.entryConfirmCount > 0
            val count = if (same) c.entryConfirmCount + 1 else 1
            val startTs = if (same && c.entryConfirmStartTs > 0L) c.entryConfirmStartTs else f.ts
            c = c.copy(entryConfirmSide = wanted, entryConfirmCount = count, entryConfirmStartTs = startTs)
            if (count >= ENTRY_CONFIRMATIONS && f.ts - startTs >= ENTRY_CONFIRM_MIN_SPAN_MS) {
                c = open(repo, c, f, ticks, wanted)
            }
            return c
        }

        c = clearPending(c)
        val side = c.paperSide
        val best = if (side == "LONG") max(c.bestPrice, f.price) else if (c.bestPrice <= 0.0) f.price else minOf(c.bestPrice, f.price)
        c = c.copy(bestPrice = best)
        val heldSeconds = (f.ts - c.entryTs) / 1000L
        val currentRet = sideReturnPct(side, c.entryPrice, f.price)
        val bestRet = sideReturnPct(side, c.entryPrice, best)
        val cfg = repo.currentConfig()
        val risk = if (c.riskStopPct > 0.0 && c.riskTrailActivationPct > 0.0 && c.riskTrailDistancePct > 0.0 && c.riskMinHoldSeconds > 0L) {
            DynamicRiskParams(c.riskStopPct, c.riskTrailActivationPct, c.riskTrailDistancePct, c.riskMinHoldSeconds, 0.0)
        } else {
            DynamicRisk.fromMarketTicks(ticks, f).also { r ->
                c = c.copy(riskStopPct = r.stopPct, riskTrailActivationPct = r.trailActivationPct, riskTrailDistancePct = r.trailDistancePct, riskMinHoldSeconds = r.minHoldSeconds)
            }
        }

        val exitReason = when {
            currentRet <= -risk.stopPct -> "dynamic protective stop"
            bestRet >= risk.trailActivationPct && (bestRet - currentRet) >= risk.trailDistancePct -> "dynamic profit trail"
            continuousFeed && heldSeconds >= risk.minHoldSeconds && side == "LONG" && f.score <= -cfg.flip -> "LONG thesis failed on confirmed reversal"
            continuousFeed && heldSeconds >= risk.minHoldSeconds && side == "SHORT" && f.score >= cfg.flip -> "SHORT thesis failed on confirmed reversal"
            continuousFeed && heldSeconds >= risk.minHoldSeconds && kotlin.math.abs(f.score) <= cfg.exit -> "signal faded below exit threshold"
            else -> null
        }

        if (exitReason != null) {
            // V3.0.10 intentionally does not instantly flip. The opposite side must survive
            // the same fresh-tick confirmation and re-entry cooldown as every other entry.
            c = close(repo, c, f, exitReason)
        }
        return c
    }

    fun forceFlat(repo: AppRepository, c: CandidateState, reason: String = "15:15 IST force-flat"): CandidateState {
        if (c.paperSide == "FLAT" || c.lastLtp <= 0.0) return clearPending(c).copy(status = "SESSION_LOCKED")
        val f = SignalFeature(System.currentTimeMillis(), c.lastLtp, c.score, c.rvol, c.vwapPct, c.trend)
        return clearPending(close(repo, c, f, reason)).copy(status = "SESSION_LOCKED")
    }

    private fun open(repo: AppRepository, c: CandidateState, f: SignalFeature, ticks: List<MarketTick>, side: String, reason: String = "signal confirmed"): CandidateState {
        val qty = floor(repo.notional() / f.price).toInt()
        if (qty <= 0) return c
        val risk = DynamicRisk.fromMarketTicks(ticks, f)
        val updated = c.copy(
            paperSide = side,
            entryPrice = f.price,
            entryTs = f.ts,
            qty = qty,
            bestPrice = f.price,
            riskStopPct = risk.stopPct,
            riskTrailActivationPct = risk.trailActivationPct,
            riskTrailDistancePct = risk.trailDistancePct,
            riskMinHoldSeconds = risk.minHoldSeconds,
            entryConfirmSide = "",
            entryConfirmCount = 0,
            entryConfirmStartTs = 0L
        )
        repo.logTrade(TradeEvent(f.ts, c.id, c.symbol, side, "OPEN", f.price, qty, 0.0,
            "$side $reason • 3-tick confirmed • AUTO risk stop=${"%.2f".format(risk.stopPct)}% trail=${"%.2f".format(risk.trailActivationPct)}/${"%.2f".format(risk.trailDistancePct)}% hold=${risk.minHoldSeconds}s",
            f.score, f.rvol, f.vwapPct, 0.0))
        return updated
    }

    private fun close(repo: AppRepository, c: CandidateState, f: SignalFeature, reason: String): CandidateState {
        val realised = pnl(c.paperSide, c.entryPrice, f.price, c.qty)
        val mfe = pnl(c.paperSide, c.entryPrice, c.bestPrice, c.qty).coerceAtLeast(0.0)
        repo.logTrade(TradeEvent(f.ts, c.id, c.symbol, c.paperSide, "CLOSE", f.price, c.qty, realised, reason,
            f.score, f.rvol, f.vwapPct, mfe))
        return c.copy(
            paperSide = "FLAT", entryPrice = 0.0, entryTs = 0L, qty = 0, bestPrice = 0.0,
            realisedPnl = c.realisedPnl + realised,
            riskStopPct = 0.0, riskTrailActivationPct = 0.0, riskTrailDistancePct = 0.0, riskMinHoldSeconds = 0L,
            lastExitTs = f.ts,
            entryConfirmSide = "", entryConfirmCount = 0, entryConfirmStartTs = 0L
        )
    }

    fun unrealisedPnl(c: CandidateState): Double {
        if (c.paperSide == "FLAT" || c.entryPrice <= 0.0 || c.lastLtp <= 0.0) return 0.0
        return pnl(c.paperSide, c.entryPrice, c.lastLtp, c.qty)
    }
}
''')

# Replay uses the same tick sanitation, confirmation and cooldown rules as live paper mode.
(src / 'ReplayEngine.kt').write_text(r'''package com.multyfi.intraday.mobile

import kotlin.math.floor
import kotlin.math.max

class ReplayEngine {
    private data class SimTrade(val pnl: Double)
    private companion object {
        const val ENTRY_CONFIRMATIONS = 3
        const val ENTRY_CONFIRM_MIN_SPAN_MS = 3_000L
        const val REENTRY_COOLDOWN_MS = 90_000L
    }

    fun learn(repo: AppRepository): LearningResult {
        val now = System.currentTimeMillis()
        val champion = repo.currentConfig()
        val sessions = repo.replaySessions()
            .mapNotNull { (id, rawTicks) ->
                val ticks = MarketDataGuard.sanitizeTicks(rawTicks)
                if (ticks.size >= 24) id to SignalMath.series(ticks) else null
            }
            .filter { it.second.size >= 24 }
            .sortedBy { it.second.firstOrNull()?.ts ?: Long.MAX_VALUE }

        if (sessions.size < 6) {
            return LearningResult(now, false, false,
                "Collecting evidence: ${sessions.size}/6 completed replay sessions. The Champion is unchanged.",
                sessions.size, 0, 0, repo.evidenceVersion(), champion, champion, champion,
                LearningMetrics(), LearningMetrics(), LearningMetrics())
        }

        val split = max(4, (sessions.size * 0.75).toInt()).coerceAtMost(sessions.size - 2)
        val train = sessions.take(split)
        val validation = sessions.drop(split)
        val candidates = mutableListOf<SignalConfig>()
        for (de in listOf(-0.06, -0.03, 0.0, 0.03, 0.06)) for (df in listOf(-0.06, -0.03, 0.0, 0.03, 0.06)) for (dx in listOf(-0.04, 0.0, 0.04)) {
            candidates += SignalConfig((champion.enter + de).coerceIn(0.42, 0.90), (champion.flip + df).coerceIn(0.50, 0.95), (champion.exit + dx).coerceIn(0.08, 0.40))
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
        } else "KEPT CHAMPION: " + gates.joinToString("; ") + "."
        val after = if (promoted) challenger else champion
        return LearningResult(now, true, promoted, reason, sessions.size, train.size, validation.size, repo.evidenceVersion(), champion, challenger, after, trainM, valM, champVal)
    }

    private fun metrics(sessions: List<Pair<String, List<SignalFeature>>>, cfg: SignalConfig, repo: AppRepository): LearningMetrics {
        val trades = sessions.flatMap { simulate(it.second, cfg, repo) }
        if (trades.isEmpty()) return LearningMetrics()
        val wins = trades.count { it.pnl > 0.0 }
        var running = 0.0; var peak = 0.0; var dd = 0.0; var gp = 0.0; var gl = 0.0
        trades.forEach { t -> running += t.pnl; peak = max(peak, running); dd = max(dd, peak - running); if (t.pnl > 0.0) gp += t.pnl else gl += -t.pnl }
        val pf = if (gl <= 0.0) if (gp > 0.0) 9.99 else 0.0 else gp / gl
        return LearningMetrics(trades.size, wins, wins.toDouble() / trades.size.toDouble(), trades.sumOf { it.pnl }, dd, pf)
    }

    private fun simulate(points: List<SignalFeature>, cfg: SignalConfig, repo: AppRepository): List<SimTrade> {
        if (points.size < 2) return emptyList()
        val out = mutableListOf<SimTrade>()
        var side = "FLAT"; var entry = 0.0; var entryTs = 0L; var qty = 0; var best = 0.0
        var risk = DynamicRiskParams(0.40, 0.45, 0.18, 30L, 0.0)
        var lastExitTs = 0L
        var pendingSide = ""; var pendingCount = 0; var pendingStartTs = 0L

        fun signedReturn(price: Double): Double { val raw = if (entry > 0.0) (price / entry - 1.0) * 100.0 else 0.0; return if (side == "LONG") raw else -raw }
        fun resetPending() { pendingSide = ""; pendingCount = 0; pendingStartTs = 0L }
        fun close(price: Double, ts: Long) {
            if (side == "FLAT") return
            val p = if (side == "LONG") (price - entry) * qty else (entry - price) * qty
            out += SimTrade(p)
            side = "FLAT"; entry = 0.0; entryTs = 0L; qty = 0; best = 0.0; lastExitTs = ts; resetPending()
        }
        fun open(s: String, p: SignalFeature, index: Int) {
            val q = floor(repo.notional() / p.price).toInt(); if (q <= 0) return
            side = s; entry = p.price; entryTs = p.ts; qty = q; best = p.price; risk = DynamicRisk.fromSignalFeatures(points, index); resetPending()
        }

        points.forEachIndexed { i, p ->
            val continuous = DynamicRisk.hasRecentContinuity(points, i)
            if (side == "FLAT") {
                if (!continuous || (lastExitTs > 0L && p.ts - lastExitTs < REENTRY_COOLDOWN_MS)) {
                    resetPending()
                } else {
                    val wanted = when { p.score >= cfg.enter -> "LONG"; p.score <= -cfg.enter -> "SHORT"; else -> "" }
                    if (wanted.isBlank()) resetPending() else {
                        if (pendingSide == wanted && pendingCount > 0) pendingCount += 1 else { pendingSide = wanted; pendingCount = 1; pendingStartTs = p.ts }
                        if (pendingCount >= ENTRY_CONFIRMATIONS && p.ts - pendingStartTs >= ENTRY_CONFIRM_MIN_SPAN_MS) open(wanted, p, i)
                    }
                }
            } else {
                best = if (side == "LONG") max(best, p.price) else minOf(best, p.price)
                val currentRet = signedReturn(p.price); val bestRet = signedReturn(best); val held = (p.ts - entryTs) / 1000L
                val reverse = continuous && held >= risk.minHoldSeconds && ((side == "LONG" && p.score <= -cfg.flip) || (side == "SHORT" && p.score >= cfg.flip))
                val fade = continuous && held >= risk.minHoldSeconds && kotlin.math.abs(p.score) <= cfg.exit
                val stop = currentRet <= -risk.stopPct
                val trail = bestRet >= risk.trailActivationPct && (bestRet - currentRet) >= risk.trailDistancePct
                if (stop || trail || reverse || fade || i == points.lastIndex) close(p.price, p.ts)
            }
        }
        if (side != "FLAT") close(points.last().price, points.last().ts)
        return out
    }

    private fun pct(v: Double) = "%.1f%%".format(v * 100.0)
    private fun money(v: Double) = "%.0f".format(v)
}
''')

# UI and diagnostic version / explanatory status.
p = src / 'MainActivity.kt'
s = p.read_text()
s = s.replace('Daily-adaptive paper intelligence • V3.0.9', 'Daily-adaptive paper intelligence • V3.0.10', 1)
hook = '        addCard(resilienceCard, bottom = 20)\n\n'
if hook not in s:
    raise SystemExit('V3.0.9 resilience settings hook not found')
extra = '''        val integrityCard = cardBox(16, greenSoft)\n        integrityCard.addView(t("MARKET DATA INTEGRITY — AUTO", 14f, green, true))\n        integrityCard.addView(t("Groww exchange last-trade time is preferred over phone receipt time. Duplicate/out-of-order snapshots, stale trade timestamps and regressing cumulative-volume snapshots are filtered. Fresh entries require 3 confirming exchange-time ticks and a 90-second cooldown after every exit; instant flip re-entries are disabled.", 13f, text).apply { setPadding(0, dp(6), 0, 0) })\n        addCard(integrityCard, bottom = 20)\n\n'''
s = s.replace(hook, hook + extra, 1)
needle = '        box.addView(t("${c.trend} • score ${"%.2f".format(Locale.US, c.score)} • RVOL ${"%.2f".format(Locale.US, c.rvol)}× • VWAP ${signedPct(c.vwapPct)}", 13f, muted).apply { setPadding(0, dp(7), 0, 0) })\n'
if needle in s:
    repl = needle + '''        if (c.paperSide == "FLAT" && c.entryConfirmCount > 0) {\n            box.addView(t("ENTRY CONFIRM • ${c.entryConfirmSide} ${c.entryConfirmCount}/3", 12f, purple, true).apply { setPadding(0, dp(5), 0, 0) })\n        }\n'''
    s = s.replace(needle, repl, 1)
p.write_text(s)

p = src / 'DiagnosticExporter.kt'
s = p.read_text()
s = s.replace('V3.0.9 — FULL DAILY DIAGNOSTIC', 'V3.0.10 — FULL DAILY DIAGNOSTIC', 1)
s = s.replace('App version: 3.0.9', 'App version: 3.0.10', 1)
hook = '            appendLine("New-entry warm-up remaining seconds: ${((repo.feedEntryResumeTs() - System.currentTimeMillis()).coerceAtLeast(0L) / 1000L)}")\n'
if hook not in s:
    raise SystemExit('V3.0.9 diagnostic feed hook not found')
extra = '''            appendLine("Market data integrity: Groww last_trade_time preferred; duplicate/out-of-order, stale and cumulative-volume-regression snapshots filtered")\n            appendLine("Entry guard: 3 fresh confirmations over >=3s; 90s cooldown after exits; instant flip re-entry disabled")\n'''
s = s.replace(hook, hook + extra, 1)
old = ' | autoMinHoldSeconds=${x.riskMinHoldSeconds} | score='
new = ' | autoMinHoldSeconds=${x.riskMinHoldSeconds} | lastExitTs=${x.lastExitTs} | entryConfirm=${x.entryConfirmSide}:${x.entryConfirmCount} | score='
if old in s:
    s = s.replace(old, new, 1)
p.write_text(s)

# Build-time assertions: fail rather than ship a partially transformed APK.
assert 'versionCode = 310' in (base / 'app/build.gradle.kts').read_text()
assert 'versionName = "3.0.10"' in (base / 'app/build.gradle.kts').read_text()
assert 'minSdk = 26' in (base / 'app/build.gradle.kts').read_text()
assert 'lastTradeTime' in (src / 'Models.kt').read_text()
assert 'last_trade_time' in (src / 'GrowwClient.kt').read_text()
assert 'MarketDataGuard.evaluate' in (src / 'MultyfiNotificationService.kt').read_text()
assert 'VOLUME_REGRESSION' in (src / 'MarketDataGuard.kt').read_text()
assert 'ENTRY_CONFIRMATIONS = 3' in (src / 'PaperEngine.kt').read_text()
assert 'REENTRY_COOLDOWN_MS = 90_000L' in (src / 'PaperEngine.kt').read_text()
assert 'MarketDataGuard.sanitizeTicks' in (src / 'ReplayEngine.kt').read_text()
assert 'MARKET DATA INTEGRITY — AUTO' in (src / 'MainActivity.kt').read_text()
assert 'MULTYFI INTRADAY MOBILE V3.0.10' in (src / 'DiagnosticExporter.kt').read_text()
