package com.intradayone.mobile.core

import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min

/**
 * Symmetric dual-direction intraday engine.
 * LONG and SHORT are first-class states: every tick computes both bullish and bearish evidence.
 * A reversal evaluates the opposite setup independently and can be proposed after the existing
 * position is flattened.
 */
class SignalEngine(var config: SignalConfig = SignalConfig()) {
    private val ticks = ArrayDeque<Tick>()
    private var lastActionAt = 0L

    fun reset() { ticks.clear(); lastActionAt = 0L }

    fun onTick(t: Tick, position: Position): SignalDecision {
        ticks.add(t)
        while (ticks.size > 160) ticks.removeFirst()
        if (ticks.size < 12) return hold("warming up")
        if (t.spreadPct > config.maxSpreadPct) return hold("spread guard")
        if (t.tsMs - lastActionAt < config.cooldownMs) return hold("cooldown")

        val p = ticks.map { it.ltp }
        val fast = ema(p.takeLast(min(8, p.size)), 4)
        val slow = ema(p.takeLast(min(24, p.size)), 12)
        val emaEdge = normalized((fast - slow) / max(t.ltp, 0.01), 0.0025)
        val rocFast = normalized((p.last() - p[p.size - 5]) / max(p[p.size - 5], 0.01), 0.0035)
        val rocSlow = normalized((p.last() - p[p.size - 10]) / max(p[p.size - 10], 0.01), 0.0070)
        val acceleration = normalized((p.last() - 2 * p[p.size - 3] + p[p.size - 6]) / max(t.ltp, 0.01), 0.0020)
        val depthImbalance = if (t.bidQty + t.askQty > 0) {
            ((t.bidQty - t.askQty) / (t.bidQty + t.askQty)).coerceIn(-1.0, 1.0)
        } else 0.0

        val recent = ticks.toList()
        val volumeNow = recent.last().volume
        val volumePast = recent[recent.size - 6].volume
        val volumeExpansion = if (volumePast > 0.0 && volumeNow >= volumePast) {
            ((volumeNow - volumePast) / max(volumePast, 1.0)).coerceIn(0.0, 1.0)
        } else 0.0
        val impulseDirection = (0.60 * rocFast + 0.40 * acceleration).coerceIn(-1.0, 1.0)
        val directionalVolume = volumeExpansion * impulseDirection

        val signedEdge = (
            0.27 * emaEdge +
                0.23 * rocFast +
                0.16 * rocSlow +
                0.19 * depthImbalance +
                0.10 * acceleration +
                0.05 * directionalVolume
            ).coerceIn(-1.0, 1.0)

        val longScore = signedEdge.coerceAtLeast(0.0)
        val shortScore = (-signedEdge).coerceAtLeast(0.0)
        val dominantScore = if (longScore >= shortScore) longScore else -shortScore
        val heldMs = if (position.side == Side.FLAT) Long.MAX_VALUE else t.tsMs - position.openedAtMs

        val decision = when (position.side) {
            Side.FLAT -> when {
                longScore >= config.enterScore -> SignalDecision(
                    SignalAction.ENTER_LONG, longScore, dominantScore,
                    "LONG edge: momentum + depth + acceleration"
                )
                shortScore >= config.enterScore -> SignalDecision(
                    SignalAction.ENTER_SHORT, shortScore, dominantScore,
                    "SHORT edge: sell pressure + downside momentum + breakdown"
                )
                else -> hold("no clean dual-direction edge", dominantScore)
            }
            Side.LONG -> when {
                heldMs < config.minHoldMs -> hold("minimum hold", dominantScore)
                shortScore >= config.flipScore -> SignalDecision(
                    SignalAction.FLIP_SHORT, shortScore, dominantScore,
                    "LONG invalidated; independent SHORT edge confirmed"
                )
                longScore < config.exitScore -> SignalDecision(
                    SignalAction.EXIT, 1.0 - longScore, dominantScore,
                    "LONG edge faded"
                )
                else -> hold("LONG intact", dominantScore)
            }
            Side.SHORT -> when {
                heldMs < config.minHoldMs -> hold("minimum hold", dominantScore)
                longScore >= config.flipScore -> SignalDecision(
                    SignalAction.FLIP_LONG, longScore, dominantScore,
                    "SHORT invalidated; independent LONG edge confirmed"
                )
                shortScore < config.exitScore -> SignalDecision(
                    SignalAction.EXIT, 1.0 - shortScore, dominantScore,
                    "SHORT edge faded"
                )
                else -> hold("SHORT intact", dominantScore)
            }
        }

        if (decision.action != SignalAction.HOLD) lastActionAt = t.tsMs
        return decision
    }

    private fun hold(reason: String, score: Double = 0.0) =
        SignalDecision(SignalAction.HOLD, abs(score).coerceIn(0.0, 1.0), score, reason)

    private fun ema(values: List<Double>, period: Int): Double {
        val alpha = 2.0 / (period + 1.0)
        var e = values.first()
        for (v in values.drop(1)) e = alpha * v + (1 - alpha) * e
        return e
    }

    private fun normalized(v: Double, scale: Double): Double = (v / scale).coerceIn(-1.0, 1.0)
}
