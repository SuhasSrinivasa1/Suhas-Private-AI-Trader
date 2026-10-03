package com.suhas.iposentinel

object LocalStrategyCatalog {
    private data class Family(
        val id: String,
        val name: String,
        val phase: String,
        val description: String
    )

    private val families = listOf(
        Family("preopen_equilibrium", "Pre-open Equilibrium", "LISTING_DAY", "Price discovery stability and auction imbalance."),
        Family("opening_drive", "Opening Drive", "LISTING_DAY", "Strong early directional expansion after continuous trading opens."),
        Family("orb_5m", "5m Opening Range Breakout", "LISTING_DAY", "Break and hold outside the first five-minute range."),
        Family("orb_15m", "15m Opening Range Breakout", "LISTING_DAY", "Break and hold outside the first fifteen-minute range."),
        Family("gap_go_fade", "Gap Continuation / Fade", "LISTING_DAY", "Continuation or rejection of the listing premium/discount."),
        Family("vwap_hold_reclaim", "VWAP Hold / Reclaim", "ALL", "Acceptance, pullback and reclaim around VWAP."),
        Family("breakout_retest", "Breakout Retest", "ALL", "Breakout followed by successful retest and continuation."),
        Family("failed_breakout", "Failed Breakout / Breakdown", "ALL", "Failure at an obvious level followed by reversal."),
        Family("liquidity_sweep", "Liquidity Sweep", "ALL", "Sweep of visible liquidity followed by rejection or continuation."),
        Family("exhaustion_reversal", "Exhaustion Reversal", "ALL", "Volume/velocity exhaustion near an extreme."),
        Family("orderflow_tape", "Order Flow + Tape Acceleration", "ALL", "Depth imbalance and trade-rate acceleration."),
        Family("relative_strength", "Relative Strength", "ALL", "Outperformance/underperformance versus NIFTY and sector."),
        Family("circuit_pressure", "Circuit Pressure", "LISTING_DAY", "Queue pressure, fill probability and circuit proximity."),
        Family("avwap_reclaim", "Listing AVWAP Reclaim", "D1_D30", "Reclaim/hold around listing-anchored VWAP."),
        Family("healthy_pullback", "Healthy Pullback", "D2_D10", "Controlled retracement with structure intact."),
        Family("post_ipo_base", "Post-IPO Base Breakout", "D5_D30", "Breakout from a multi-session post-listing base."),
        Family("volume_revival", "Volume Revival", "D5_D30", "Renewed participation after a quiet digestion period."),
        Family("intraday_fade", "Post-listing Intraday Fade", "D1_D30", "Eligible intraday short after structural weakness is confirmed."),
        Family("closing_continuation", "Closing Strength Continuation", "D0_D30", "Late-session strength used for delivery hold/next-day continuation.")
    )

    fun summary(note: String): StrategySummary {
        val rows = families.map {
            StrategyFamilyStats(
                familyId = it.id,
                name = it.name,
                phase = it.phase,
                description = it.description,
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
            totalStrategyFamilies = rows.size,
            testedFamilies = 0,
            champions = 0,
            challengers = 0,
            untestedFamilies = rows.size,
            topFive = emptyList(),
            families = rows,
            rankingNote = note,
            evidenceSource = "LOCAL_CATALOG"
        )
    }
}
