package com.intradayone.mobile.core

import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sign

/**
 * Symmetric intraday engine: LONG and SHORT are first-class outcomes.
 * Multyfi selects the stock; price/volume/microstructure decide direction.
 */
class SignalEngine(var config: SignalConfig = SignalConfig()) {
    private val ticks = ArrayDeque<Tick>()
    private var lastActionAt = 0L

    fun reset() { ticks.clear(); lastActionAt = 0L }

    fun onTick(t: Tick, position: Position, context: RecommendationContext? = null): SignalDecision {
        ticks.add(t)
        while (ticks.size > 240) ticks.removeFirst()
        if (ticks.size < 12) return hold("warming up")
        if (t.spreadPct > config.maxSpreadPct) return hold("spread guard")
        if (t.tsMs - lastActionAt < config.cooldownMs) return hold("cooldown")

        val a = ticks.toList()
        val p = a.map { it.ltp }
        val fast = ema(p.takeLast(min(10, p.size)), 4)
        val slow = ema(p.takeLast(min(30, p.size)), 14)
        val emaEdge = normalized((fast - slow) / max(t.ltp, 0.01), 0.0022)

        val rocFastRaw = (p.last() - p[p.size - 5]) / max(p[p.size - 5], 0.01)
        val rocFast = normalized(rocFastRaw, 0.0025)
        val rocSlowRaw = (p.last() - p[p.size - 11]) / max(p[p.size - 11], 0.01)
        val rocSlow = normalized(rocSlowRaw, 0.0055)

        val book = if (t.bidQty + t.askQty > 0) (t.bidQty - t.askQty) / (t.bidQty + t.askQty) else 0.0
        val acceleration = normalized((p.last() - 2 * p[p.size - 3] + p[p.size - 6]) / max(t.ltp, 0.01), 0.0016)

        val volumeDeltas = a.zipWithNext { x, y -> max(0.0, y.volume - x.volume) }
        val recentVol = volumeDeltas.takeLast(min(5, volumeDeltas.size)).averageOrZero()
        val olderSlice = volumeDeltas.dropLast(min(5, volumeDeltas.size)).takeLast(20)
        val baselineVol = olderSlice.averageOrZero()
        val relativeVolume = when {
            baselineVol > 0.0 -> (recentVol / baselineVol).coerceIn(0.10, 8.0)
            recentVol > 0.0 -> 1.25
            else -> 1.0
        }
        val volumeImpulse = normalized(relativeVolume - 1.0, 2.0) * sign(rocFastRaw)

        val vwap = rollingVwap(a.takeLast(min(80, a.size)))
        val vwapEdgeRaw = if (vwap > 0.0) (t.ltp - vwap) / max(t.ltp, 0.01) else 0.0
        val vwapEdge = normalized(vwapEdgeRaw, 0.0030)

        val recentReturns = p.zipWithNext { x, y -> abs((y - x) / max(x, 0.01)) }
            .takeLast(min(20, p.size - 1))
        val volatilityPct = recentReturns.averageOrZero() * 100.0

        val rangeWindow = p.dropLast(2).takeLast(min(40, p.size - 2))
        val rangeBoost = if (rangeWindow.size >= 10) {
            val high = rangeWindow.maxOrNull() ?: t.ltp
            val low = rangeWindow.minOrNull() ?: t.ltp
            when {
                t.ltp > high && rocFastRaw > 0 && relativeVolume >= 1.15 -> 0.08
                t.ltp < low && rocFastRaw < 0 && relativeVolume >= 1.15 -> -0.08
                else -> 0.0
            }
        } else 0.0

        // Provider levels are context only. A FREE recommendation that immediately fails
        // below its entry band can strengthen a SHORT thesis rather than force a BUY.
        val levelBoost = context?.let { c ->
            val low = c.entryLow
            val high = c.entryHigh
            when {
                low != null && t.ltp < low && rocFastRaw < 0 -> if (c.isFreeRecommendation) -0.10 else -0.07
                high != null && t.ltp > high && rocFastRaw > 0 -> if (c.isFreeRecommendation) 0.08 else 0.06
                else -> 0.0
            }
        } ?: 0.0

        val score = (
            0.20 * emaEdge +
                0.18 * rocFast +
                0.10 * rocSlow +
                0.15 * book +
                0.10 * acceleration +
                0.12 * vwapEdge +
                0.15 * volumeImpulse +
                rangeBoost + levelBoost
            ).coerceIn(-1.0, 1.0)

        val confidence = abs(score).coerceIn(0.0, 1.0)
        val heldMs = if (position.side == Side.FLAT) Long.MAX_VALUE else t.tsMs - position.openedAtMs
        val contextText = "rv=${"%.2f".format(relativeVolume)} vwap=${"%.2f".format(vwapEdgeRaw * 100)}%"

        val decision = when (position.side) {
            Side.FLAT -> when {
                score >= config.enterScore -> SignalDecision(SignalAction.ENTER_LONG, confidence, score, "LONG edge • $contextText", relativeVolume, vwapEdgeRaw, volatilityPct)
                score <= -config.enterScore -> SignalDecision(SignalAction.ENTER_SHORT, confidence, score, "SHORT edge • $contextText", relativeVolume, vwapEdgeRaw, volatilityPct)
                else -> hold("no clean long/short edge • $contextText", score, relativeVolume, vwapEdgeRaw, volatilityPct)
            }
            Side.LONG -> when {
                heldMs < config.minHoldMs -> hold("minimum hold • $contextText", score, relativeVolume, vwapEdgeRaw, volatilityPct)
                score <= -config.flipScore -> SignalDecision(SignalAction.FLIP_SHORT, confidence, score, "LONG failed; SHORT reversal confirmed • $contextText", relativeVolume, vwapEdgeRaw, volatilityPct)
                score < config.exitScore -> SignalDecision(SignalAction.EXIT, (1 - confidence).coerceIn(0.0, 1.0), score, "LONG edge faded • $contextText", relativeVolume, vwapEdgeRaw, volatilityPct)
                else -> hold("LONG intact • $contextText", score, relativeVolume, vwapEdgeRaw, volatilityPct)
            }
            Side.SHORT -> when {
                heldMs < config.minHoldMs -> hold("minimum hold • $contextText", score, relativeVolume, vwapEdgeRaw, volatilityPct)
                score >= config.flipScore -> SignalDecision(SignalAction.FLIP_LONG, confidence, score, "SHORT failed; LONG reversal confirmed • $contextText", relativeVolume, vwapEdgeRaw, volatilityPct)
                score > -config.exitScore -> SignalDecision(SignalAction.EXIT, (1 - confidence).coerceIn(0.0, 1.0), score, "SHORT edge faded • $contextText", relativeVolume, vwapEdgeRaw, volatilityPct)
                else -> hold("SHORT intact • $contextText", score, relativeVolume, vwapEdgeRaw, volatilityPct)
            }
        }
        if (decision.action != SignalAction.HOLD) lastActionAt = t.tsMs
        return decision
    }

    private fun rollingVwap(window: List<Tick>): Double {
        if (window.size < 2) return window.lastOrNull()?.ltp ?: 0.0
        var weighted = 0.0
        var vol = 0.0
        for (i in 1 until window.size) {
            val dv = max(0.0, window[i].volume - window[i - 1].volume)
            if (dv > 0.0) {
                weighted += window[i].ltp * dv
                vol += dv
            }
        }
        return if (vol > 0.0) weighted / vol else window.map { it.ltp }.average()
    }

    private fun hold(
        reason: String,
        score: Double = 0.0,
        relativeVolume: Double = 1.0,
        vwapEdge: Double = 0.0,
        volatilityPct: Double = 0.0
    ) = SignalDecision(SignalAction.HOLD, abs(score), score, reason, relativeVolume, vwapEdge, volatilityPct)

    private fun ema(values: List<Double>, period: Int): Double {
        val alpha = 2.0 / (period + 1.0)
        var e = values.first()
        for (v in values.drop(1)) e = alpha * v + (1 - alpha) * e
        return e
    }

    private fun normalized(v: Double, scale: Double): Double = (v / scale).coerceIn(-1.0, 1.0)
    private fun List<Double>.averageOrZero(): Double = if (isEmpty()) 0.0 else average()
}
