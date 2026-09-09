package com.multyfi.dailylearner

data class SignalConfig(
    val enter: Double = 0.68,
    val flip: Double = 0.78,
    val exit: Double = 0.20
)

data class TradeEvent(
    val ts: Long,
    val symbol: String,
    val side: String,
    val action: String,
    val price: Double,
    val pnl: Double = 0.0,
    val reason: String = "",
    val score: Double = 0.0,
    val rvol: Double = 1.0,
    val vwapPct: Double = 0.0
)

data class SessionSummary(
    val date: String,
    val trades: Int,
    val wins: Int,
    val losses: Int,
    val pnl: Double,
    val maxDrawdown: Double,
    val profitFactor: Double,
    val accuracy: Double
)

data class LearningResult(
    val trainAccuracy: Double,
    val validationAccuracy: Double,
    val replayPnl: Double,
    val championBefore: SignalConfig,
    val challenger: SignalConfig,
    val championAfter: SignalConfig,
    val promoted: Boolean,
    val reason: String,
    val sessionsUsed: Int
)
