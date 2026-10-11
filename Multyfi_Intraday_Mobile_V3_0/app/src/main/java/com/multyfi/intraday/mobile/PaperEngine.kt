package com.multyfi.intraday.mobile

import kotlin.math.floor
import kotlin.math.max

object PaperEngine {
    private fun sideReturnPct(side: String, entry: Double, price: Double): Double {
        if (entry <= 0.0) return 0.0
        val raw = (price / entry - 1.0) * 100.0
        return if (side == "LONG") raw else -raw
    }

    private fun pnl(side: String, entry: Double, price: Double, qty: Int): Double {
        return if (side == "LONG") (price - entry) * qty else (entry - price) * qty
    }

    fun onQuote(repo: AppRepository, c0: CandidateState, ticks: List<MarketTick>): CandidateState {
        if (ticks.isEmpty()) return c0
        val f = SignalMath.latest(ticks)
        var c = c0.copy(
            lastLtp = f.price,
            lastUpdatedTs = f.ts,
            score = f.score,
            rvol = f.rvol,
            vwapPct = f.vwapPct,
            trend = f.trend
        )

        if (MarketClock.shouldForceFlat()) {
            if (c.paperSide != "FLAT") c = close(repo, c, f, "15:15 IST force-flat")
            return c.copy(status = "SESSION_LOCKED")
        }

        if (c.paperSide == "FLAT") {
            if (MarketClock.canOpenNewPaperRisk()) {
                val cfg = repo.currentConfig()
                if (f.score >= cfg.enter) c = open(repo, c, f, "LONG")
                else if (f.score <= -cfg.enter) c = open(repo, c, f, "SHORT")
            }
            return c
        }

        val side = c.paperSide
        val best = when (side) {
            "LONG" -> max(c.bestPrice, f.price)
            else -> if (c.bestPrice <= 0.0) f.price else minOf(c.bestPrice, f.price)
        }
        c = c.copy(bestPrice = best)
        val heldSeconds = (f.ts - c.entryTs) / 1000L
        val currentRet = sideReturnPct(side, c.entryPrice, f.price)
        val bestRet = sideReturnPct(side, c.entryPrice, best)
        val cfg = repo.currentConfig()

        val exitReason = when {
            currentRet <= -repo.stopPct() -> "protective stop"
            bestRet >= repo.trailActivationPct() && (bestRet - currentRet) >= repo.trailDistancePct() -> "profit trail"
            heldSeconds >= repo.minHoldSeconds() && side == "LONG" && f.score <= -cfg.flip -> "LONG thesis failed on confirmed reversal"
            heldSeconds >= repo.minHoldSeconds() && side == "SHORT" && f.score >= cfg.flip -> "SHORT thesis failed on confirmed reversal"
            heldSeconds >= repo.minHoldSeconds() && kotlin.math.abs(f.score) <= cfg.exit -> "signal faded below exit threshold"
            else -> null
        }

        if (exitReason != null) {
            val oldSide = c.paperSide
            c = close(repo, c, f, exitReason)
            if (exitReason.contains("confirmed reversal") && MarketClock.canOpenNewPaperRisk()) {
                val newSide = if (oldSide == "LONG") "SHORT" else "LONG"
                c = open(repo, c, f, newSide, "confirmed flip")
            }
        }
        return c
    }

    fun forceFlat(repo: AppRepository, c: CandidateState, reason: String = "15:15 IST force-flat"): CandidateState {
        if (c.paperSide == "FLAT" || c.lastLtp <= 0.0) return c.copy(status = "SESSION_LOCKED")
        val f = SignalFeature(System.currentTimeMillis(), c.lastLtp, c.score, c.rvol, c.vwapPct, c.trend)
        return close(repo, c, f, reason).copy(status = "SESSION_LOCKED")
    }

    private fun open(repo: AppRepository, c: CandidateState, f: SignalFeature, side: String, reason: String = "signal confirmed"): CandidateState {
        val qty = max(1, floor(repo.notional() / f.price).toInt())
        val updated = c.copy(
            paperSide = side,
            entryPrice = f.price,
            entryTs = f.ts,
            qty = qty,
            bestPrice = f.price
        )
        repo.logTrade(
            TradeEvent(f.ts, c.id, c.symbol, side, "OPEN", f.price, qty, 0.0,
                "$side $reason", f.score, f.rvol, f.vwapPct, 0.0)
        )
        return updated
    }

    private fun close(repo: AppRepository, c: CandidateState, f: SignalFeature, reason: String): CandidateState {
        val realised = pnl(c.paperSide, c.entryPrice, f.price, c.qty)
        val mfe = pnl(c.paperSide, c.entryPrice, c.bestPrice, c.qty).coerceAtLeast(0.0)
        repo.logTrade(
            TradeEvent(f.ts, c.id, c.symbol, c.paperSide, "CLOSE", f.price, c.qty, realised, reason,
                f.score, f.rvol, f.vwapPct, mfe)
        )
        return c.copy(
            paperSide = "FLAT",
            entryPrice = 0.0,
            entryTs = 0L,
            qty = 0,
            bestPrice = 0.0,
            realisedPnl = c.realisedPnl + realised
        )
    }

    fun unrealisedPnl(c: CandidateState): Double {
        if (c.paperSide == "FLAT" || c.entryPrice <= 0.0 || c.lastLtp <= 0.0) return 0.0
        return pnl(c.paperSide, c.entryPrice, c.lastLtp, c.qty)
    }
}
