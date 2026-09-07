package com.intradayone.mobile.core

import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sign

/**
 * V2.2 time-normalised intraday engine.
 *
 * Key fixes versus the earlier tick-count engine:
 * - Features are measured over elapsed time, not "last N REST responses".
 * - Relative volume uses cumulative-volume rate over time windows, so bursty REST
 *   snapshots do not pin RVOL at the cap.
 * - VWAP is accumulated for the full candidate session, not the last ~80 samples.
 * - Same-side re-entry is locked after an exit unless a genuinely new structure forms.
 * - Reversals are sequential: an open leg is EXITed first; the opposite side is
 *   considered only after the broker/paper position is observed FLAT.
 */
class SignalEngine(var config: SignalConfig = SignalConfig()) {
    private val ticks = ArrayDeque<Tick>()
    private var lastActionAt = 0L

    private var sessionWeightedPxVol = 0.0
    private var sessionVolume = 0.0
    private var lastSeenVolume = 0.0

    private var previousObservedSide = Side.FLAT
    private var blockedSide: Side = Side.FLAT
    private var blockedUntilMs = 0L
    private var lastExitPrice = 0.0

    private var confirmSide = Side.FLAT
    private var confirmSinceMs = 0L

    private var trackedOpenSide = Side.FLAT
    private var bestOpenPnlPct = 0.0

    fun reset() {
        ticks.clear()
        lastActionAt = 0L
        sessionWeightedPxVol = 0.0
        sessionVolume = 0.0
        lastSeenVolume = 0.0
        previousObservedSide = Side.FLAT
        blockedSide = Side.FLAT
        blockedUntilMs = 0L
        lastExitPrice = 0.0
        confirmSide = Side.FLAT
        confirmSinceMs = 0L
        trackedOpenSide = Side.FLAT
        bestOpenPnlPct = 0.0
    }

    fun onTick(t: Tick, position: Position, context: RecommendationContext? = null): SignalDecision {
        observePositionTransition(t, position)
        updateSessionVwap(t)

        ticks.add(t)
        val cutoff = t.tsMs - 120_000L
        while (ticks.size > 16 && ticks.first().tsMs < cutoff) ticks.removeFirst()
        while (ticks.size > 800) ticks.removeFirst()

        if (ticks.size < 6 || spanMs() < 1_500L) return hold("warming up")
        if (t.spreadPct > config.maxSpreadPct) return hold("spread guard")
        if (t.tsMs - lastActionAt < config.cooldownMs) return hold("cooldown")

        val r1 = returnPct(t.tsMs, 1_000L)
        val r3 = returnPct(t.tsMs, 3_000L)
        val r8 = returnPct(t.tsMs, 8_000L)
        val r20 = returnPct(t.tsMs, 20_000L)
        val prev1 = returnPctBetween(t.tsMs - 2_000L, t.tsMs - 1_000L)

        val fastMomentum = normalized(r3, 0.22)
        val mediumMomentum = normalized(r8, 0.45)
        val slowMomentum = normalized(r20, 0.90)
        val acceleration = normalized(r1 - prev1, 0.10)

        val book = if (t.bidQty + t.askQty > 0.0) {
            ((t.bidQty - t.askQty) / (t.bidQty + t.askQty)).coerceIn(-1.0, 1.0)
        } else 0.0

        val relativeVolume = robustRelativeVolume(t.tsMs)
        val volumeImpulse = normalized(relativeVolume - 1.0, 1.8) * sign(r3)

        val vwap = if (sessionVolume > 0.0) sessionWeightedPxVol / sessionVolume else averagePrice(20_000L)
        val vwapEdgeRaw = if (vwap > 0.0) ((t.ltp - vwap) / vwap) * 100.0 else 0.0
        val vwapEdge = normalized(vwapEdgeRaw, 0.35)

        val structure = structure(t.tsMs)
        val structureBoost = when (structure) {
            Structure.RISING -> 0.12
            Structure.FALLING -> -0.12
            Structure.SIDEWAYS -> 0.0
            Structure.MIXED -> 0.0
        }

        val breakout = breakoutSignal(t.tsMs, relativeVolume)
        val providerBoost = providerContextBoost(context, t, r3, structure)

        val score = (
            0.20 * fastMomentum +
                0.13 * mediumMomentum +
                0.07 * slowMomentum +
                0.09 * acceleration +
                0.08 * book +
                0.13 * volumeImpulse +
                0.13 * vwapEdge +
                structureBoost +
                breakout +
                providerBoost
            ).coerceIn(-1.0, 1.0)

        val confidence = abs(score).coerceIn(0.0, 1.0)
        val volatilityPct = realisedVolatilityPct(t.tsMs)
        val heldMs = if (position.side == Side.FLAT) Long.MAX_VALUE else t.tsMs - position.openedAtMs
        val pnlPct = openPnlPct(position, t.ltp)
        if (position.side != Side.FLAT) bestOpenPnlPct = max(bestOpenPnlPct, pnlPct)

        val regimeText = when (structure) {
            Structure.RISING -> "RISING STRUCTURE"
            Structure.FALLING -> "FALLING STRUCTURE"
            Structure.SIDEWAYS -> "SIDEWAYS/FLAT"
            Structure.MIXED -> "MIXED STRUCTURE"
        }
        val contextText = "rv=${"%.2f".format(relativeVolume)} vwap=${"%.2f".format(vwapEdgeRaw)}% • $regimeText"

        val decision = when (position.side) {
            Side.FLAT -> decideFlat(t, score, confidence, relativeVolume, vwapEdgeRaw, volatilityPct, structure, breakout, contextText)
            Side.LONG -> decideLong(t, position, heldMs, pnlPct, score, confidence, relativeVolume, vwapEdgeRaw, volatilityPct, structure, contextText)
            Side.SHORT -> decideShort(t, position, heldMs, pnlPct, score, confidence, relativeVolume, vwapEdgeRaw, volatilityPct, structure, contextText)
        }

        if (decision.action != SignalAction.HOLD) lastActionAt = t.tsMs
        return decision
    }

    private fun decideFlat(
        t: Tick,
        score: Double,
        confidence: Double,
        rv: Double,
        vwapEdge: Double,
        vol: Double,
        structure: Structure,
        breakout: Double,
        contextText: String
    ): SignalDecision {
        if (structure == Structure.SIDEWAYS && abs(score) < 0.82) {
            clearConfirmation()
            return hold("sideways abstain • $contextText", score, rv, vwapEdge, vol)
        }

        val candidate = when {
            score >= config.enterScore && structure != Structure.FALLING -> Side.LONG
            score <= -config.enterScore && structure != Structure.RISING -> Side.SHORT
            else -> Side.FLAT
        }
        if (candidate == Side.FLAT) {
            clearConfirmation()
            return hold("no clean long/short edge • $contextText", score, rv, vwapEdge, vol)
        }

        val blocked = candidate == blockedSide && t.tsMs < blockedUntilMs
        if (blocked && !freshStructureBreak(candidate, t.ltp, structure, rv, breakout)) {
            clearConfirmation()
            return hold("${candidate.name} re-entry lock; waiting for new structure • $contextText", score, rv, vwapEdge, vol)
        }

        if (confirmSide != candidate) {
            confirmSide = candidate
            confirmSinceMs = t.tsMs
            return hold("${candidate.name} confirming • $contextText", score, rv, vwapEdge, vol)
        }

        val urgent = abs(breakout) >= 0.10 && rv >= 1.25 && abs(score) >= max(config.enterScore, 0.70)
        if (!urgent && t.tsMs - confirmSinceMs < 350L) {
            return hold("${candidate.name} confirming • $contextText", score, rv, vwapEdge, vol)
        }

        clearConfirmation()
        return if (candidate == Side.LONG) {
            SignalDecision(SignalAction.ENTER_LONG, confidence, score, "LONG confirmed • $contextText", rv, vwapEdge / 100.0, vol)
        } else {
            SignalDecision(SignalAction.ENTER_SHORT, confidence, score, "SHORT confirmed • $contextText", rv, vwapEdge / 100.0, vol)
        }
    }

    private fun decideLong(
        t: Tick,
        position: Position,
        heldMs: Long,
        pnlPct: Double,
        score: Double,
        confidence: Double,
        rv: Double,
        vwapEdge: Double,
        vol: Double,
        structure: Structure,
        contextText: String
    ): SignalDecision {
        clearConfirmation()
        if (heldMs < max(config.minHoldMs, 1_000L)) return hold("minimum hold • $contextText", score, rv, vwapEdge, vol)

        if (profitTrailTriggered(pnlPct)) {
            return SignalDecision(SignalAction.EXIT, confidence, score, "LONG profit trail • $contextText", rv, vwapEdge / 100.0, vol)
        }

        val strongReversal = score <= -max(config.flipScore, 0.70) || (structure == Structure.FALLING && score < -0.30)
        if (strongReversal) {
            return SignalDecision(SignalAction.EXIT, confidence, score, "LONG invalidated; exit before any SHORT • $contextText", rv, vwapEdge / 100.0, vol)
        }

        if (pnlPct > 0.05 && score < 0.08 && structure != Structure.RISING) {
            return SignalDecision(SignalAction.EXIT, (1.0 - confidence).coerceIn(0.0, 1.0), score, "LONG edge faded after profit • $contextText", rv, vwapEdge / 100.0, vol)
        }

        if (pnlPct <= -0.08 && score < -0.22 && structure != Structure.RISING) {
            return SignalDecision(SignalAction.EXIT, confidence, score, "LONG thesis failed • $contextText", rv, vwapEdge / 100.0, vol)
        }

        return hold("LONG intact • $contextText", score, rv, vwapEdge, vol)
    }

    private fun decideShort(
        t: Tick,
        position: Position,
        heldMs: Long,
        pnlPct: Double,
        score: Double,
        confidence: Double,
        rv: Double,
        vwapEdge: Double,
        vol: Double,
        structure: Structure,
        contextText: String
    ): SignalDecision {
        clearConfirmation()
        if (heldMs < max(config.minHoldMs, 1_000L)) return hold("minimum hold • $contextText", score, rv, vwapEdge, vol)

        if (profitTrailTriggered(pnlPct)) {
            return SignalDecision(SignalAction.EXIT, confidence, score, "SHORT profit trail • $contextText", rv, vwapEdge / 100.0, vol)
        }

        val strongReversal = score >= max(config.flipScore, 0.70) || (structure == Structure.RISING && score > 0.30)
        if (strongReversal) {
            return SignalDecision(SignalAction.EXIT, confidence, score, "SHORT invalidated; exit before any LONG • $contextText", rv, vwapEdge / 100.0, vol)
        }

        if (pnlPct > 0.05 && score > -0.08 && structure != Structure.FALLING) {
            return SignalDecision(SignalAction.EXIT, (1.0 - confidence).coerceIn(0.0, 1.0), score, "SHORT edge faded after profit • $contextText", rv, vwapEdge / 100.0, vol)
        }

        if (pnlPct <= -0.08 && score > 0.22 && structure != Structure.FALLING) {
            return SignalDecision(SignalAction.EXIT, confidence, score, "SHORT thesis failed • $contextText", rv, vwapEdge / 100.0, vol)
        }

        return hold("SHORT intact • $contextText", score, rv, vwapEdge, vol)
    }

    private fun observePositionTransition(t: Tick, position: Position) {
        if (previousObservedSide != Side.FLAT && position.side == Side.FLAT) {
            blockedSide = previousObservedSide
            blockedUntilMs = t.tsMs + 12_000L
            lastExitPrice = t.ltp
            trackedOpenSide = Side.FLAT
            bestOpenPnlPct = 0.0
        }
        if (position.side != Side.FLAT && trackedOpenSide != position.side) {
            trackedOpenSide = position.side
            bestOpenPnlPct = 0.0
        }
        previousObservedSide = position.side
    }

    private fun freshStructureBreak(side: Side, price: Double, structure: Structure, rv: Double, breakout: Double): Boolean {
        if (lastExitPrice <= 0.0 || rv < 1.15) return false
        val movePct = ((price - lastExitPrice) / lastExitPrice) * 100.0
        return when (side) {
            Side.LONG -> structure == Structure.RISING && movePct >= 0.15 && breakout > 0.0
            Side.SHORT -> structure == Structure.FALLING && movePct <= -0.15 && breakout < 0.0
            Side.FLAT -> false
        }
    }

    private fun profitTrailTriggered(currentPnlPct: Double): Boolean {
        val peak = bestOpenPnlPct
        if (peak < 0.22) return false
        val allowedGiveback = when {
            peak >= 0.80 -> 0.20
            peak >= 0.50 -> 0.16
            peak >= 0.30 -> 0.12
            else -> 0.09
        }
        return currentPnlPct > 0.03 && peak - currentPnlPct >= allowedGiveback
    }

    private fun openPnlPct(position: Position, price: Double): Double {
        if (position.side == Side.FLAT || position.entryPrice <= 0.0) return 0.0
        val raw = ((price - position.entryPrice) / position.entryPrice) * 100.0
        return if (position.side == Side.LONG) raw else -raw
    }

    private fun updateSessionVwap(t: Tick) {
        if (lastSeenVolume <= 0.0) {
            lastSeenVolume = t.volume
            return
        }
        if (t.volume < lastSeenVolume) {
            sessionWeightedPxVol = 0.0
            sessionVolume = 0.0
            lastSeenVolume = t.volume
            return
        }
        val dv = t.volume - lastSeenVolume
        if (dv > 0.0) {
            sessionWeightedPxVol += t.ltp * dv
            sessionVolume += dv
            lastSeenVolume = t.volume
        }
    }

    private fun robustRelativeVolume(nowMs: Long): Double {
        val recent = volumeRate(nowMs, 6_000L)
        val baseline = volumeRate(nowMs, 45_000L)
        if (recent <= 0.0 || baseline <= 0.0) return 1.0
        return (recent / baseline).coerceIn(0.35, 4.0)
    }

    private fun volumeRate(nowMs: Long, windowMs: Long): Double {
        val now = tickAtOrBefore(nowMs) ?: return 0.0
        val old = tickAtOrBefore(nowMs - windowMs) ?: ticks.firstOrNull() ?: return 0.0
        val dt = (now.tsMs - old.tsMs).coerceAtLeast(1L) / 1000.0
        val dv = (now.volume - old.volume).coerceAtLeast(0.0)
        return dv / dt
    }

    private fun returnPct(nowMs: Long, horizonMs: Long): Double {
        val now = tickAtOrBefore(nowMs) ?: return 0.0
        val old = tickAtOrBefore(nowMs - horizonMs) ?: ticks.firstOrNull() ?: return 0.0
        if (old.ltp <= 0.0) return 0.0
        return ((now.ltp - old.ltp) / old.ltp) * 100.0
    }

    private fun returnPctBetween(startMs: Long, endMs: Long): Double {
        val a = tickAtOrBefore(startMs) ?: return 0.0
        val b = tickAtOrBefore(endMs) ?: return 0.0
        if (a.ltp <= 0.0) return 0.0
        return ((b.ltp - a.ltp) / a.ltp) * 100.0
    }

    private fun averagePrice(windowMs: Long): Double {
        val now = ticks.lastOrNull()?.tsMs ?: return 0.0
        val values = ticks.filter { it.tsMs >= now - windowMs }.map { it.ltp }
        return if (values.isEmpty()) ticks.lastOrNull()?.ltp ?: 0.0 else values.average()
    }

    private fun realisedVolatilityPct(nowMs: Long): Double {
        val sample = ticks.filter { it.tsMs >= nowMs - 20_000L }
        if (sample.size < 3) return 0.0
        val moves = sample.zipWithNext { a, b -> if (a.ltp > 0.0) abs((b.ltp - a.ltp) / a.ltp) * 100.0 else 0.0 }
        return if (moves.isEmpty()) 0.0 else moves.average()
    }

    private enum class Structure { RISING, FALLING, SIDEWAYS, MIXED }

    private fun structure(nowMs: Long): Structure {
        val old = ticks.filter { it.tsMs in (nowMs - 24_000L)..(nowMs - 12_000L) }.map { it.ltp }
        val recent = ticks.filter { it.tsMs > nowMs - 12_000L }.map { it.ltp }
        if (old.size < 3 || recent.size < 3) return Structure.MIXED

        val all = old + recent
        val minAll = all.minOrNull() ?: return Structure.MIXED
        val maxAll = all.maxOrNull() ?: return Structure.MIXED
        val rangePct = if (minAll > 0.0) ((maxAll - minAll) / minAll) * 100.0 else 0.0
        val net = returnPct(nowMs, 20_000L)
        if (rangePct < 0.16 && abs(net) < 0.10) return Structure.SIDEWAYS

        val oldHigh = old.maxOrNull() ?: return Structure.MIXED
        val oldLow = old.minOrNull() ?: return Structure.MIXED
        val newHigh = recent.maxOrNull() ?: return Structure.MIXED
        val newLow = recent.minOrNull() ?: return Structure.MIXED
        val hh = ((newHigh - oldHigh) / max(oldHigh, 0.01)) * 100.0
        val hl = ((newLow - oldLow) / max(oldLow, 0.01)) * 100.0
        return when {
            hh >= 0.06 && hl >= 0.04 -> Structure.RISING
            hh <= -0.04 && hl <= -0.06 -> Structure.FALLING
            else -> Structure.MIXED
        }
    }

    private fun breakoutSignal(nowMs: Long, rv: Double): Double {
        val current = ticks.lastOrNull()?.ltp ?: return 0.0
        val prior = ticks.filter { it.tsMs in (nowMs - 20_000L)..(nowMs - 1_500L) }.map { it.ltp }
        if (prior.size < 5) return 0.0
        val high = prior.maxOrNull() ?: return 0.0
        val low = prior.minOrNull() ?: return 0.0
        val up = ((current - high) / max(high, 0.01)) * 100.0
        val down = ((current - low) / max(low, 0.01)) * 100.0
        return when {
            up >= 0.05 && rv >= 1.15 -> 0.10
            down <= -0.05 && rv >= 1.15 -> -0.10
            else -> 0.0
        }
    }

    private fun providerContextBoost(context: RecommendationContext?, t: Tick, r3: Double, structure: Structure): Double {
        val c = context ?: return 0.0
        var boost = 0.0
        c.entryLow?.let { low ->
            if (t.ltp < low && r3 < -0.04 && structure != Structure.RISING) boost -= if (c.isFreeRecommendation) 0.08 else 0.05
        }
        c.entryHigh?.let { high ->
            if (t.ltp > high && r3 > 0.04 && structure != Structure.FALLING) boost += if (c.isFreeRecommendation) 0.06 else 0.04
        }
        if (c.providerExitSignal && r3 < -0.03 && structure != Structure.RISING) boost -= 0.08
        return boost
    }

    private fun tickAtOrBefore(tsMs: Long): Tick? {
        for (i in ticks.size - 1 downTo 0) {
            val t = ticks.elementAt(i)
            if (t.tsMs <= tsMs) return t
        }
        return ticks.firstOrNull()
    }

    private fun spanMs(): Long = if (ticks.size < 2) 0L else ticks.last().tsMs - ticks.first().tsMs

    private fun clearConfirmation() {
        confirmSide = Side.FLAT
        confirmSinceMs = 0L
    }

    private fun hold(
        reason: String,
        score: Double = 0.0,
        relativeVolume: Double = 1.0,
        vwapEdge: Double = 0.0,
        volatilityPct: Double = 0.0
    ) = SignalDecision(SignalAction.HOLD, abs(score), score, reason, relativeVolume, vwapEdge / 100.0, volatilityPct)

    private fun normalized(v: Double, scale: Double): Double = (v / scale).coerceIn(-1.0, 1.0)
}
