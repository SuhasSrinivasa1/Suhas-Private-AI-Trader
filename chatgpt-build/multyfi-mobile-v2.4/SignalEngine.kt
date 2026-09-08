package com.intradayone.mobile.core

import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min

/**
 * V2.4 playbook intraday engine.
 *
 * Instead of compressing every condition into one directional score, V2.4 evaluates
 * dedicated LONG/SHORT playbooks (trend, breakout/breakdown, VWAP, reversal) and lets
 * the strongest clean setup compete with the opposite side. Session-only penalties
 * reduce repeated failed playbooks without changing the persistent model mid-trade.
 */
class SignalEngine(var config: SignalConfig = SignalConfig()) {
    private val ticks = ArrayDeque<Tick>()
    private var lastActionAt = 0L

    private var sessionWeightedPxVol = 0.0
    private var sessionVolume = 0.0
    private var lastSeenVolume = 0.0

    private var previousObservedSide = Side.FLAT
    private var blockedSide = Side.FLAT
    private var blockedUntilMs = 0L
    private var lastExitPrice = 0.0

    private var confirmSide = Side.FLAT
    private var confirmPlaybook = Playbook.NONE
    private var confirmSinceMs = 0L

    private var trackedOpenSide = Side.FLAT
    private var trackedEntryPrice = 0.0
    private var trackedPlaybook = Playbook.NONE
    private var pendingEntryPlaybook = Playbook.NONE
    private var bestOpenPnlPct = 0.0

    private var longSessionPenalty = 0.0
    private var shortSessionPenalty = 0.0
    private val playbookPenalty = mutableMapOf<Playbook, Double>()

    private enum class Structure { RISING, FALLING, SIDEWAYS, MIXED }
    private enum class Playbook {
        NONE,
        LONG_TREND,
        SHORT_TREND,
        LONG_BREAKOUT,
        SHORT_BREAKDOWN,
        LONG_VWAP,
        SHORT_VWAP,
        LONG_REVERSAL,
        SHORT_REVERSAL
    }

    private data class Setup(val side: Side, val playbook: Playbook, val quality: Double)

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
        confirmPlaybook = Playbook.NONE
        confirmSinceMs = 0L
        trackedOpenSide = Side.FLAT
        trackedEntryPrice = 0.0
        trackedPlaybook = Playbook.NONE
        pendingEntryPlaybook = Playbook.NONE
        bestOpenPnlPct = 0.0
        longSessionPenalty = 0.0
        shortSessionPenalty = 0.0
        playbookPenalty.clear()
    }

    fun onTick(t: Tick, position: Position, context: RecommendationContext? = null): SignalDecision {
        observePositionTransition(t, position)
        updateSessionVwap(t)

        ticks.add(t)
        val cutoff = t.tsMs - 180_000L
        while (ticks.size > 20 && ticks.first().tsMs < cutoff) ticks.removeFirst()
        while (ticks.size > 1200) ticks.removeFirst()

        if (ticks.size < 7 || spanMs() < 2_500L) return hold("warming up")
        if (t.ltp <= 0.0) return hold("invalid LTP")
        if (t.spreadPct > config.maxSpreadPct) return hold("spread guard")
        if (t.tsMs - lastActionAt < config.cooldownMs) return hold("cooldown")

        val r1 = returnPct(t.tsMs, 1_000L)
        val r3 = returnPct(t.tsMs, 3_000L)
        val r8 = returnPct(t.tsMs, 8_000L)
        val r20 = returnPct(t.tsMs, 20_000L)
        val prev1 = returnPctBetween(t.tsMs - 2_000L, t.tsMs - 1_000L)
        val acceleration = r1 - prev1

        val book = if (t.bidQty + t.askQty > 0.0) {
            ((t.bidQty - t.askQty) / (t.bidQty + t.askQty)).coerceIn(-1.0, 1.0)
        } else 0.0

        val rv = robustRelativeVolume(t.tsMs)
        val vwap = if (sessionVolume > 0.0) sessionWeightedPxVol / sessionVolume else averagePrice(25_000L)
        val vwapEdge = if (vwap > 0.0) ((t.ltp - vwap) / vwap) * 100.0 else 0.0
        val structure = structure(t.tsMs)
        val breakout = breakoutStrength(t.tsMs, rv)
        val reversal = reversalStrength(t.tsMs, r1, r8)
        val volatilityPct = realisedVolatilityPct(t.tsMs)

        val longSetup = bestLongSetup(structure, r1, r3, r8, r20, acceleration, book, rv, vwapEdge, breakout, reversal, context, t)
        val shortSetup = bestShortSetup(structure, r1, r3, r8, r20, acceleration, book, rv, vwapEdge, breakout, reversal, context, t)

        val longQuality = applyPenalty(longSetup)
        val shortQuality = applyPenalty(shortSetup)
        val signedEdge = (longQuality - shortQuality).coerceIn(-1.0, 1.0)
        val confidence = max(longQuality, shortQuality).coerceIn(0.0, 1.0)
        val heldMs = if (position.side == Side.FLAT) Long.MAX_VALUE else t.tsMs - position.openedAtMs
        val pnlPct = openPnlPct(position, t.ltp)
        if (position.side != Side.FLAT) bestOpenPnlPct = max(bestOpenPnlPct, pnlPct)

        val contextText = "L=${"%.2f".format(longQuality)} ${longSetup.playbook.name} " +
            "S=${"%.2f".format(shortQuality)} ${shortSetup.playbook.name} " +
            "rv=${"%.2f".format(rv)} vwap=${"%.2f".format(vwapEdge)}% ${structure.name}"

        val decision = when (position.side) {
            Side.FLAT -> decideFlat(t, longSetup.copy(quality = longQuality), shortSetup.copy(quality = shortQuality), signedEdge, rv, vwapEdge, volatilityPct, structure, breakout, contextText)
            Side.LONG -> decideOpen(t, position, Side.LONG, heldMs, pnlPct, longQuality, shortQuality, signedEdge, confidence, rv, vwapEdge, volatilityPct, structure, contextText)
            Side.SHORT -> decideOpen(t, position, Side.SHORT, heldMs, pnlPct, shortQuality, longQuality, signedEdge, confidence, rv, vwapEdge, volatilityPct, structure, contextText)
        }

        if (decision.action != SignalAction.HOLD) lastActionAt = t.tsMs
        return decision
    }

    private fun bestLongSetup(
        structure: Structure,
        r1: Double,
        r3: Double,
        r8: Double,
        r20: Double,
        acceleration: Double,
        book: Double,
        rv: Double,
        vwapEdge: Double,
        breakout: Double,
        reversal: Double,
        context: RecommendationContext?,
        t: Tick
    ): Setup {
        val fast = positiveNorm(r3, 0.20)
        val medium = positiveNorm(r8, 0.42)
        val slow = positiveNorm(r20, 0.85)
        val accel = positiveNorm(acceleration, 0.10)
        val vwap = positiveNorm(vwapEdge, 0.30)
        val volume = positiveNorm(rv - 1.0, 1.8)
        val bid = max(book, 0.0)
        val trend = when (structure) {
            Structure.RISING -> 1.0
            Structure.MIXED -> 0.35
            else -> 0.0
        }
        val provider = providerLongBoost(context, t, r3, structure)

        val trendQ = (0.30 * trend + 0.19 * fast + 0.13 * medium + 0.08 * slow + 0.10 * vwap + 0.08 * volume + 0.06 * bid + 0.06 * accel + provider).coerceIn(0.0, 1.0)
        val breakoutQ = (0.34 * max(breakout, 0.0) + 0.22 * fast + 0.16 * volume + 0.10 * accel + 0.08 * vwap + 0.05 * bid + 0.05 * trend + provider).coerceIn(0.0, 1.0)
        val vwapQ = (0.28 * vwap + 0.24 * fast + 0.13 * medium + 0.11 * accel + 0.10 * trend + 0.08 * volume + 0.06 * bid + provider).coerceIn(0.0, 1.0)
        val reversalQ = (0.36 * max(reversal, 0.0) + 0.22 * positiveNorm(r1, 0.10) + 0.12 * accel + 0.10 * bid + 0.08 * volume + 0.06 * positiveNorm(-vwapEdge, 0.40) + 0.06 * (if (structure == Structure.FALLING) 0.4 else 0.0) + provider).coerceIn(0.0, 1.0)

        return listOf(
            Setup(Side.LONG, Playbook.LONG_TREND, trendQ),
            Setup(Side.LONG, Playbook.LONG_BREAKOUT, breakoutQ),
            Setup(Side.LONG, Playbook.LONG_VWAP, vwapQ),
            Setup(Side.LONG, Playbook.LONG_REVERSAL, reversalQ)
        ).maxByOrNull { it.quality } ?: Setup(Side.LONG, Playbook.NONE, 0.0)
    }

    private fun bestShortSetup(
        structure: Structure,
        r1: Double,
        r3: Double,
        r8: Double,
        r20: Double,
        acceleration: Double,
        book: Double,
        rv: Double,
        vwapEdge: Double,
        breakout: Double,
        reversal: Double,
        context: RecommendationContext?,
        t: Tick
    ): Setup {
        val fast = positiveNorm(-r3, 0.20)
        val medium = positiveNorm(-r8, 0.42)
        val slow = positiveNorm(-r20, 0.85)
        val accel = positiveNorm(-acceleration, 0.10)
        val vwap = positiveNorm(-vwapEdge, 0.30)
        val volume = positiveNorm(rv - 1.0, 1.8)
        val ask = max(-book, 0.0)
        val trend = when (structure) {
            Structure.FALLING -> 1.0
            Structure.MIXED -> 0.35
            else -> 0.0
        }
        val provider = providerShortBoost(context, t, r3, structure)

        val trendQ = (0.30 * trend + 0.19 * fast + 0.13 * medium + 0.08 * slow + 0.10 * vwap + 0.08 * volume + 0.06 * ask + 0.06 * accel + provider).coerceIn(0.0, 1.0)
        val breakdownQ = (0.34 * max(-breakout, 0.0) + 0.22 * fast + 0.16 * volume + 0.10 * accel + 0.08 * vwap + 0.05 * ask + 0.05 * trend + provider).coerceIn(0.0, 1.0)
        val vwapQ = (0.28 * vwap + 0.24 * fast + 0.13 * medium + 0.11 * accel + 0.10 * trend + 0.08 * volume + 0.06 * ask + provider).coerceIn(0.0, 1.0)
        val reversalQ = (0.36 * max(-reversal, 0.0) + 0.22 * positiveNorm(-r1, 0.10) + 0.12 * accel + 0.10 * ask + 0.08 * volume + 0.06 * positiveNorm(vwapEdge, 0.40) + 0.06 * (if (structure == Structure.RISING) 0.4 else 0.0) + provider).coerceIn(0.0, 1.0)

        return listOf(
            Setup(Side.SHORT, Playbook.SHORT_TREND, trendQ),
            Setup(Side.SHORT, Playbook.SHORT_BREAKDOWN, breakdownQ),
            Setup(Side.SHORT, Playbook.SHORT_VWAP, vwapQ),
            Setup(Side.SHORT, Playbook.SHORT_REVERSAL, reversalQ)
        ).maxByOrNull { it.quality } ?: Setup(Side.SHORT, Playbook.NONE, 0.0)
    }

    private fun decideFlat(
        t: Tick,
        longSetup: Setup,
        shortSetup: Setup,
        signedEdge: Double,
        rv: Double,
        vwapEdge: Double,
        vol: Double,
        structure: Structure,
        breakout: Double,
        contextText: String
    ): SignalDecision {
        val best = if (longSetup.quality >= shortSetup.quality) longSetup else shortSetup
        val other = if (best.side == Side.LONG) shortSetup else longSetup
        val margin = best.quality - other.quality
        val baseThreshold = (config.enterScore - 0.05).coerceIn(0.57, 0.67)
        val directionalThreshold = when {
            best.playbook == Playbook.LONG_BREAKOUT || best.playbook == Playbook.SHORT_BREAKDOWN -> baseThreshold - 0.03
            best.playbook == Playbook.LONG_REVERSAL || best.playbook == Playbook.SHORT_REVERSAL -> baseThreshold + 0.02
            else -> baseThreshold
        }
        val cleanBreak = abs(breakout) >= 0.70 && rv >= 1.35

        if (structure == Structure.SIDEWAYS && !cleanBreak && best.quality < 0.74) {
            clearConfirmation()
            return hold("sideways abstain • $contextText", signedEdge, rv, vwapEdge, vol)
        }
        if (best.quality < directionalThreshold || margin < 0.08) {
            clearConfirmation()
            return hold("no clean playbook edge • $contextText", signedEdge, rv, vwapEdge, vol)
        }

        val blocked = best.side == blockedSide && t.tsMs < blockedUntilMs
        if (blocked && !freshStructureBreak(best.side, t.ltp, structure, rv, breakout, best.quality)) {
            clearConfirmation()
            return hold("${best.side.name} re-entry locked after prior attempt • $contextText", signedEdge, rv, vwapEdge, vol)
        }

        if (confirmSide != best.side || confirmPlaybook != best.playbook) {
            confirmSide = best.side
            confirmPlaybook = best.playbook
            confirmSinceMs = t.tsMs
            return hold("${best.playbook.name} confirming • $contextText", signedEdge, rv, vwapEdge, vol)
        }

        val urgent = cleanBreak && best.quality >= 0.72 && margin >= 0.12
        val requiredMs = if (urgent) 0L else if (best.quality >= 0.76) 250L else 550L
        if (t.tsMs - confirmSinceMs < requiredMs) {
            return hold("${best.playbook.name} confirming • $contextText", signedEdge, rv, vwapEdge, vol)
        }

        clearConfirmation()
        pendingEntryPlaybook = best.playbook
        val action = if (best.side == Side.LONG) SignalAction.ENTER_LONG else SignalAction.ENTER_SHORT
        return SignalDecision(action, best.quality, signedEdge, "${best.playbook.name} ENTER • $contextText", rv, vwapEdge / 100.0, vol)
    }

    private fun decideOpen(
        t: Tick,
        position: Position,
        side: Side,
        heldMs: Long,
        pnlPct: Double,
        ownQuality: Double,
        oppositeQuality: Double,
        signedEdge: Double,
        confidence: Double,
        rv: Double,
        vwapEdge: Double,
        vol: Double,
        structure: Structure,
        contextText: String
    ): SignalDecision {
        clearConfirmation()
        if (heldMs < max(config.minHoldMs, 900L)) return hold("minimum hold • $contextText", signedEdge, rv, vwapEdge, vol)

        if (pnlPct <= -0.28) {
            return SignalDecision(SignalAction.EXIT, confidence, signedEdge, "${side.name} hard adverse move • $contextText", rv, vwapEdge / 100.0, vol)
        }
        if (profitTrailTriggered(pnlPct)) {
            return SignalDecision(SignalAction.EXIT, confidence, signedEdge, "${side.name} profit trail • $contextText", rv, vwapEdge / 100.0, vol)
        }

        val oppositeStrong = oppositeQuality >= max(0.62, config.flipScore - 0.08)
        val ownWeak = ownQuality <= 0.44
        if (oppositeStrong && (ownWeak || pnlPct < -0.06)) {
            return SignalDecision(SignalAction.EXIT, confidence, signedEdge, "${side.name} invalidated; flatten before reversal • $contextText", rv, vwapEdge / 100.0, vol)
        }

        if (pnlPct >= 0.12 && ownQuality < 0.48) {
            return SignalDecision(SignalAction.EXIT, confidence, signedEdge, "${side.name} edge faded; bank move • $contextText", rv, vwapEdge / 100.0, vol)
        }

        val structureAgainst = (side == Side.LONG && structure == Structure.FALLING) || (side == Side.SHORT && structure == Structure.RISING)
        if (pnlPct <= -0.10 && ownQuality < 0.52 && (structureAgainst || oppositeQuality > ownQuality + 0.10)) {
            return SignalDecision(SignalAction.EXIT, confidence, signedEdge, "${side.name} thesis failed quickly • $contextText", rv, vwapEdge / 100.0, vol)
        }

        return hold("${side.name} intact • $contextText", signedEdge, rv, vwapEdge, vol)
    }

    private fun applyPenalty(setup: Setup): Double {
        val sidePenalty = if (setup.side == Side.LONG) longSessionPenalty else shortSessionPenalty
        val pbPenalty = playbookPenalty[setup.playbook] ?: 0.0
        return (setup.quality - sidePenalty - pbPenalty).coerceIn(0.0, 1.0)
    }

    private fun observePositionTransition(t: Tick, position: Position) {
        if (position.side != Side.FLAT && trackedOpenSide != position.side) {
            trackedOpenSide = position.side
            trackedEntryPrice = if (position.entryPrice > 0.0) position.entryPrice else t.ltp
            trackedPlaybook = if (pendingEntryPlaybook != Playbook.NONE) pendingEntryPlaybook else fallbackPlaybook(position.side)
            pendingEntryPlaybook = Playbook.NONE
            bestOpenPnlPct = 0.0
        }

        if (previousObservedSide != Side.FLAT && position.side == Side.FLAT) {
            val resultPct = if (trackedEntryPrice > 0.0) {
                val raw = ((t.ltp - trackedEntryPrice) / trackedEntryPrice) * 100.0
                if (previousObservedSide == Side.LONG) raw else -raw
            } else 0.0
            adaptAfterClosedLeg(previousObservedSide, trackedPlaybook, resultPct)
            blockedSide = previousObservedSide
            blockedUntilMs = t.tsMs + if (resultPct < -0.03) 30_000L else 10_000L
            lastExitPrice = t.ltp
            trackedOpenSide = Side.FLAT
            trackedEntryPrice = 0.0
            trackedPlaybook = Playbook.NONE
            bestOpenPnlPct = 0.0
        }
        previousObservedSide = position.side
    }

    private fun adaptAfterClosedLeg(side: Side, playbook: Playbook, resultPct: Double) {
        if (side == Side.FLAT) return
        if (resultPct < -0.03) {
            if (side == Side.LONG) longSessionPenalty = min(0.12, longSessionPenalty + 0.035)
            else shortSessionPenalty = min(0.12, shortSessionPenalty + 0.035)
            if (playbook != Playbook.NONE) {
                playbookPenalty[playbook] = min(0.14, (playbookPenalty[playbook] ?: 0.0) + 0.045)
            }
        } else if (resultPct > 0.08) {
            if (side == Side.LONG) longSessionPenalty = max(0.0, longSessionPenalty - 0.02)
            else shortSessionPenalty = max(0.0, shortSessionPenalty - 0.02)
            if (playbook != Playbook.NONE) {
                playbookPenalty[playbook] = max(0.0, (playbookPenalty[playbook] ?: 0.0) - 0.025)
            }
        }
    }

    private fun fallbackPlaybook(side: Side): Playbook = if (side == Side.LONG) Playbook.LONG_TREND else Playbook.SHORT_TREND

    private fun freshStructureBreak(side: Side, price: Double, structure: Structure, rv: Double, breakout: Double, quality: Double): Boolean {
        if (lastExitPrice <= 0.0 || rv < 1.20 || quality < 0.70) return false
        val movePct = ((price - lastExitPrice) / lastExitPrice) * 100.0
        return when (side) {
            Side.LONG -> (structure == Structure.RISING && movePct >= 0.12 && breakout > 0.25) || (breakout > 0.80 && movePct >= 0.08)
            Side.SHORT -> (structure == Structure.FALLING && movePct <= -0.12 && breakout < -0.25) || (breakout < -0.80 && movePct <= -0.08)
            Side.FLAT -> false
        }
    }

    private fun profitTrailTriggered(currentPnlPct: Double): Boolean {
        val peak = bestOpenPnlPct
        if (peak < 0.16) return false
        val allowedGiveback = when {
            peak >= 0.80 -> 0.18
            peak >= 0.50 -> 0.14
            peak >= 0.30 -> 0.10
            peak >= 0.20 -> 0.075
            else -> 0.055
        }
        return currentPnlPct > 0.035 && peak - currentPnlPct >= allowedGiveback
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
        val recent = volumeRate(nowMs, 7_000L)
        val baseline = volumeRate(nowMs, 60_000L)
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

    private fun structure(nowMs: Long): Structure {
        val old = ticks.filter { it.tsMs in (nowMs - 30_000L)..(nowMs - 15_000L) }.map { it.ltp }
        val recent = ticks.filter { it.tsMs > nowMs - 15_000L }.map { it.ltp }
        if (old.size < 3 || recent.size < 3) return Structure.MIXED

        val all = old + recent
        val minAll = all.minOrNull() ?: return Structure.MIXED
        val maxAll = all.maxOrNull() ?: return Structure.MIXED
        val rangePct = if (minAll > 0.0) ((maxAll - minAll) / minAll) * 100.0 else 0.0
        val net = returnPct(nowMs, 25_000L)
        if (rangePct < 0.13 && abs(net) < 0.08) return Structure.SIDEWAYS

        val oldHigh = old.maxOrNull() ?: return Structure.MIXED
        val oldLow = old.minOrNull() ?: return Structure.MIXED
        val newHigh = recent.maxOrNull() ?: return Structure.MIXED
        val newLow = recent.minOrNull() ?: return Structure.MIXED
        val hh = ((newHigh - oldHigh) / max(oldHigh, 0.01)) * 100.0
        val hl = ((newLow - oldLow) / max(oldLow, 0.01)) * 100.0
        return when {
            hh >= 0.045 && hl >= 0.025 -> Structure.RISING
            hh <= -0.025 && hl <= -0.045 -> Structure.FALLING
            else -> Structure.MIXED
        }
    }

    private fun breakoutStrength(nowMs: Long, rv: Double): Double {
        val current = ticks.lastOrNull()?.ltp ?: return 0.0
        val prior = ticks.filter { it.tsMs in (nowMs - 30_000L)..(nowMs - 2_000L) }.map { it.ltp }
        if (prior.size < 6) return 0.0
        val high = prior.maxOrNull() ?: return 0.0
        val low = prior.minOrNull() ?: return 0.0
        val upPct = ((current - high) / max(high, 0.01)) * 100.0
        val downPct = ((current - low) / max(low, 0.01)) * 100.0
        val rvFactor = positiveNorm(rv - 1.0, 1.5)
        return when {
            upPct > 0.0 -> (positiveNorm(upPct, 0.16) * (0.72 + 0.28 * rvFactor)).coerceIn(0.0, 1.0)
            downPct < 0.0 -> -(positiveNorm(-downPct, 0.16) * (0.72 + 0.28 * rvFactor)).coerceIn(0.0, 1.0)
            else -> 0.0
        }
    }

    private fun reversalStrength(nowMs: Long, r1: Double, r8: Double): Double {
        val current = ticks.lastOrNull()?.ltp ?: return 0.0
        val recent = ticks.filter { it.tsMs >= nowMs - 10_000L }.map { it.ltp }
        if (recent.size < 5 || current <= 0.0) return 0.0
        val high = recent.maxOrNull() ?: return 0.0
        val low = recent.minOrNull() ?: return 0.0
        val offHigh = ((high - current) / max(high, 0.01)) * 100.0
        val offLow = ((current - low) / max(low, 0.01)) * 100.0
        val shortReversal = if (r8 >= 0.18 && r1 <= -0.035 && offHigh >= 0.07) {
            positiveNorm(r8, 0.55) * 0.45 + positiveNorm(-r1, 0.14) * 0.35 + positiveNorm(offHigh, 0.20) * 0.20
        } else 0.0
        val longReversal = if (r8 <= -0.18 && r1 >= 0.035 && offLow >= 0.07) {
            positiveNorm(-r8, 0.55) * 0.45 + positiveNorm(r1, 0.14) * 0.35 + positiveNorm(offLow, 0.20) * 0.20
        } else 0.0
        return when {
            longReversal > shortReversal -> longReversal.coerceIn(0.0, 1.0)
            shortReversal > longReversal -> -shortReversal.coerceIn(0.0, 1.0)
            else -> 0.0
        }
    }

    private fun providerLongBoost(context: RecommendationContext?, t: Tick, r3: Double, structure: Structure): Double {
        val c = context ?: return 0.0
        var boost = 0.0
        c.entryHigh?.let { high ->
            if (t.ltp > high && r3 > 0.035 && structure != Structure.FALLING) boost += if (c.isFreeRecommendation) 0.06 else 0.04
        }
        return boost
    }

    private fun providerShortBoost(context: RecommendationContext?, t: Tick, r3: Double, structure: Structure): Double {
        val c = context ?: return 0.0
        var boost = 0.0
        c.entryLow?.let { low ->
            if (t.ltp < low && r3 < -0.035 && structure != Structure.RISING) boost += if (c.isFreeRecommendation) 0.07 else 0.05
        }
        if (c.providerExitSignal && r3 < -0.025 && structure != Structure.RISING) boost += 0.08
        return boost
    }

    private fun realisedVolatilityPct(nowMs: Long): Double {
        val sample = ticks.filter { it.tsMs >= nowMs - 20_000L }
        if (sample.size < 3) return 0.0
        val moves = sample.zipWithNext { a, b -> if (a.ltp > 0.0) abs((b.ltp - a.ltp) / a.ltp) * 100.0 else 0.0 }
        return if (moves.isEmpty()) 0.0 else moves.average()
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
        confirmPlaybook = Playbook.NONE
        confirmSinceMs = 0L
    }

    private fun hold(
        reason: String,
        score: Double = 0.0,
        relativeVolume: Double = 1.0,
        vwapEdge: Double = 0.0,
        volatilityPct: Double = 0.0
    ) = SignalDecision(SignalAction.HOLD, abs(score).coerceIn(0.0, 1.0), score.coerceIn(-1.0, 1.0), reason, relativeVolume, vwapEdge / 100.0, volatilityPct)

    private fun positiveNorm(v: Double, scale: Double): Double = (v / scale).coerceIn(0.0, 1.0)
}
