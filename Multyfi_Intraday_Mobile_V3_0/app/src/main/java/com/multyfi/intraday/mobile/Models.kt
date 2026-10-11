package com.multyfi.intraday.mobile

data class SignalConfig(
    val enter: Double = 0.68,
    val flip: Double = 0.78,
    val exit: Double = 0.20
)

data class MarketTick(
    val ts: Long,
    val symbol: String,
    val price: Double,
    val volume: Long,
    val averagePrice: Double,
    val bidPrice: Double,
    val offerPrice: Double
)

data class SignalFeature(
    val ts: Long,
    val price: Double,
    val score: Double,
    val rvol: Double,
    val vwapPct: Double,
    val trend: String
)

data class CandidateState(
    val id: String,
    val symbol: String,
    val source: String,
    val acceptedTs: Long,
    val status: String = "ACTIVE",
    val lastLtp: Double = 0.0,
    val lastUpdatedTs: Long = 0L,
    val score: Double = 0.0,
    val rvol: Double = 1.0,
    val vwapPct: Double = 0.0,
    val trend: String = "WAITING",
    val paperSide: String = "FLAT",
    val entryPrice: Double = 0.0,
    val entryTs: Long = 0L,
    val qty: Int = 0,
    val bestPrice: Double = 0.0,
    val realisedPnl: Double = 0.0,
    val rawNotification: String = "",
    val notificationPackage: String = ""
)

data class TradeEvent(
    val ts: Long,
    val candidateId: String,
    val symbol: String,
    val side: String,
    val action: String,
    val price: Double,
    val qty: Int,
    val pnl: Double,
    val reason: String,
    val score: Double,
    val rvol: Double,
    val vwapPct: Double,
    val mfePnl: Double = 0.0
)

data class ActivityItem(
    val ts: Long,
    val type: String,
    val title: String,
    val detail: String,
    val severity: String = "INFO"
)

data class LearningMetrics(
    val trades: Int = 0,
    val wins: Int = 0,
    val accuracy: Double = 0.0,
    val pnl: Double = 0.0,
    val maxDrawdown: Double = 0.0,
    val profitFactor: Double = 0.0
)

data class LearningResult(
    val ts: Long,
    val evaluated: Boolean,
    val promoted: Boolean,
    val reason: String,
    val sessionsUsed: Int,
    val trainSessions: Int,
    val validationSessions: Int,
    val evidenceVersion: Long,
    val championBefore: SignalConfig,
    val challenger: SignalConfig,
    val championAfter: SignalConfig,
    val challengerTrain: LearningMetrics,
    val challengerValidation: LearningMetrics,
    val championValidation: LearningMetrics
)

data class GrowwQuote(
    val symbol: String,
    val lastPrice: Double,
    val volume: Long,
    val averagePrice: Double,
    val bidPrice: Double,
    val offerPrice: Double,
    val rawStatus: String
)
