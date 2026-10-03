package com.suhas.iposentinel

object LocalStrategyCatalog {
    private data class Entry(
        val id: String,
        val name: String,
        val phase: String,
        val description: String
    )

    private val entries = listOf(
        Entry("preopen_equilibrium", "Pre-open Equilibrium", "LISTING_DAY", "Price discovery stability and auction imbalance."),
        Entry("opening_drive", "Opening Drive", "LISTING_DAY", "Early directional expansion after continuous trading opens."),
        Entry("orb_5m", "5m Opening Range Breakout", "LISTING_DAY", "Break and hold outside the first five-minute range."),
        Entry("orb_15m", "15m Opening Range Breakout", "LISTING_DAY", "Break and hold outside the first fifteen-minute range."),
        Entry("gap_go_fade", "Gap Continuation / Fade", "LISTING_DAY", "Continuation or rejection of the listing premium or discount."),
        Entry("vwap_hold_reclaim", "VWAP Hold / Reclaim", "ALL", "Acceptance, pullback and reclaim around VWAP."),
        Entry("breakout_retest", "Breakout Retest", "ALL", "Breakout followed by a successful retest."),
        Entry("failed_breakout", "Failed Breakout / Breakdown", "ALL", "Failure at an obvious level followed by reversal."),
        Entry("liquidity_sweep", "Liquidity Sweep", "ALL", "Sweep of visible liquidity followed by rejection or continuation."),
        Entry("exhaustion_reversal", "Exhaustion Reversal", "ALL", "Volume and velocity exhaustion near an extreme."),
        Entry("orderflow_tape", "Order Flow + Tape Acceleration", "ALL", "Depth imbalance and trade-rate acceleration."),
        Entry("relative_strength", "Relative Strength", "ALL", "Performance versus NIFTY and the relevant sector."),
        Entry("circuit_pressure", "Circuit Pressure", "LISTING_DAY", "Queue pressure, fill probability and circuit proximity."),
        Entry("avwap_reclaim", "Listing AVWAP Reclaim", "D1_D30", "Reclaim or hold around listing-anchored VWAP."),
        Entry("healthy_pullback", "Healthy Pullback", "D2_D10", "Controlled retracement with trend structure intact."),
        Entry("post_ipo_base", "Post-IPO Base Breakout", "D5_D30", "Breakout from a multi-session post-listing base."),
        Entry("volume_revival", "Volume Revival", "D5_D30", "Renewed participation after quiet digestion."),
        Entry("intraday_fade", "Post-listing Intraday Fade", "D1_D30", "Eligible intraday short after structural weakness."),
        Entry("closing_continuation", "Closing Strength Continuation", "D0_D30", "Late-session strength for delivery continuation.")
    )

    fun summary(): StrategySummary {
        val families = entries.map { entry ->
            StrategyFamilyStats(
                familyId = entry.id,
                name = entry.name,
                phase = entry.phase,
                description = entry.description,
                trades = 0,
                winRatePct = 0.0,
                expectancyBps = 0.0,
                profitFactor = 0.0,
                maxDrawdownBps = 0.0,
                last20NetBps = 0.0,
                status = "RESEARCH",
                rankingScore = 0.0
            )
        }
        return StrategySummary(
            totalStrategyFamilies = families.size,
            testedFamilies = 0,
            champions = 0,
            challengers = 0,
            untestedFamilies = families.size,
            topFive = emptyList(),
            families = families,
            rankingNote = "Local strategy catalog shown. Replay evidence will populate automatically when the trading service is provisioned."
        )
    }
}
