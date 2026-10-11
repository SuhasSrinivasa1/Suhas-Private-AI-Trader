package com.multyfi.intraday.mobile

import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

object DiagnosticExporter {
    private val sdf = SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.US)

    fun build(repo: AppRepository): String {
        val metrics = repo.dayMetrics()
        val c = repo.currentConfig()
        val learn = repo.lastLearning()
        val candidates = repo.todayCandidates()
        val trades = repo.todayTrades().sortedBy { it.ts }
        val activity = repo.todayActivity().sortedBy { it.ts }
        val learningLines = repo.learningHistoryLines()
        val tickLines = repo.todayRawTickLines()

        return buildString {
            appendLine("MULTYFI INTRADAY MOBILE V3.0.1 — FULL DAILY DIAGNOSTIC")
            appendLine("Generated: ${sdf.format(Date())} IST")
            appendLine("Package: com.multyfi.intraday.mobile")
            appendLine("App version: 3.0.1")
            appendLine("Mode: PAPER ONLY — NO BROKER ORDERS")
            appendLine()

            appendLine("==================== SYSTEM ====================")
            appendLine("Groww credentials configured: ${yesNo(repo.growwCredentialsConfigured())}")
            appendLine("Groww token configured: ${yesNo(repo.accessToken().isNotBlank())}")
            appendLine("Groww token validated today: ${yesNo(repo.growwValidated())}")
            appendLine("Notification access enabled: ${yesNo(repo.notificationAccessEnabled())}")
            appendLine("Static IP whitelisted: ${repo.whitelistIp().ifBlank { "NOT SET" }}")
            appendLine("Detected public IP: ${repo.detectedIp().ifBlank { "UNKNOWN" }}")
            appendLine("Static IP verified: ${yesNo(repo.staticIpVerified())}")
            appendLine("Exchange clock: ${MarketClock.exchangeState()}")
            appendLine("Last market feed: ${if (repo.lastFeedTs() > 0) sdf.format(Date(repo.lastFeedTs())) else "NONE"}")
            appendLine("Listener heartbeat: ${if (repo.listenerHeartbeatTs() > 0) sdf.format(Date(repo.listenerHeartbeatTs())) else "NONE"}")
            appendLine("Secrets are intentionally excluded from this file.")
            appendLine()

            appendLine("==================== TODAY ====================")
            appendLine("Candidates: ${candidates.size}")
            appendLine("Closed paper legs: ${metrics.trades}")
            appendLine("Wins: ${metrics.wins}")
            appendLine("Losses: ${metrics.trades - metrics.wins}")
            appendLine("Accuracy: ${fmtPct(metrics.accuracy)}")
            appendLine("Paper P&L: ₹${money(metrics.pnl)}")
            appendLine("Profit factor: ${"%.2f".format(Locale.US, metrics.profitFactor)}")
            appendLine("Max drawdown: ₹${money(metrics.maxDrawdown)}")
            appendLine("Capture efficiency: ${fmtPct(repo.captureEfficiency())}")
            appendLine()

            appendLine("==================== ACTIVE CHAMPION ====================")
            appendLine("enter=${"%.2f".format(Locale.US, c.enter)}")
            appendLine("flip=${"%.2f".format(Locale.US, c.flip)}")
            appendLine("exit=${"%.2f".format(Locale.US, c.exit)}")
            appendLine("Evidence version: ${repo.evidenceVersion()}")
            appendLine("Learning up to date: ${yesNo(repo.learningUpToDate())}")
            appendLine()

            appendLine("==================== LAST LEARNING ====================")
            if (learn == null) {
                appendLine("No completed learning evaluation yet.")
            } else {
                appendLine("Timestamp: ${sdf.format(Date(learn.ts))}")
                appendLine("Evaluated: ${yesNo(learn.evaluated)}")
                appendLine("Decision: ${if (learn.promoted) "PROMOTED CHALLENGER" else "KEPT CHAMPION"}")
                appendLine("Reason: ${learn.reason}")
                appendLine("Sessions used: ${learn.sessionsUsed} (train=${learn.trainSessions}, validation=${learn.validationSessions})")
                appendLine("Champion before: ${cfg(learn.championBefore)}")
                appendLine("Challenger: ${cfg(learn.challenger)}")
                appendLine("Champion after: ${cfg(learn.championAfter)}")
                appendLine("Challenger train: ${met(learn.challengerTrain)}")
                appendLine("Challenger validation: ${met(learn.challengerValidation)}")
                appendLine("Champion validation: ${met(learn.championValidation)}")
            }
            appendLine()

            appendLine("==================== CANDIDATES ====================")
            candidates.forEach { x ->
                appendLine("${x.symbol} | ${x.source} | accepted=${sdf.format(Date(x.acceptedTs))} | status=${x.status} | LTP=${x.lastLtp} | paper=${x.paperSide} | realisedPnl=${x.realisedPnl} | score=${"%.3f".format(Locale.US, x.score)} | RVOL=${"%.2f".format(Locale.US, x.rvol)} | VWAP%=${"%.3f".format(Locale.US, x.vwapPct)} | trend=${x.trend}")
                appendLine("  notificationPackage=${x.notificationPackage} | raw=${x.rawNotification.replace("\n", " ")}")
            }
            if (candidates.isEmpty()) appendLine("NONE")
            appendLine()

            appendLine("==================== TRADE LOG ====================")
            trades.forEach { e ->
                appendLine("${sdf.format(Date(e.ts))} | ${e.symbol} | ${e.side} | ${e.action} | price=${e.price} | qty=${e.qty} | pnl=${e.pnl} | MFE=${e.mfePnl} | score=${e.score} | RVOL=${e.rvol} | VWAP%=${e.vwapPct} | ${e.reason}")
            }
            if (trades.isEmpty()) appendLine("NONE")
            appendLine()

            appendLine("==================== ACTIVITY / ERROR LOG ====================")
            activity.forEach { a -> appendLine("${sdf.format(Date(a.ts))} | ${a.type} | ${a.severity} | ${a.title} | ${a.detail.replace("\n", " ")}") }
            if (activity.isEmpty()) appendLine("NONE")
            appendLine()

            appendLine("==================== LEARNING HISTORY ====================")
            learningLines.forEach { appendLine(it) }
            if (learningLines.isEmpty()) appendLine("NONE")
            appendLine()

            appendLine("==================== RAW MARKET TICKS ====================")
            tickLines.forEach { appendLine(it) }
            if (tickLines.isEmpty()) appendLine("NONE")
            appendLine()

            appendLine("==================== FOOTER ====================")
            appendLine("DAILY LEARNING STATUS: ${if (repo.learningUpToDate()) "UP TO DATE" else "PENDING / INSUFFICIENT EVIDENCE"}")
            appendLine("TODAY EVIDENCE VERSION: ${repo.evidenceVersion()}")
            appendLine("TODAY INCLUDED IN LATEST LEARNING: ${yesNo(repo.learningUpToDate())}")
            appendLine("NEXT SESSION CONFIG: ${cfg(repo.currentConfig())}")
        }
    }

    private fun yesNo(v: Boolean) = if (v) "YES" else "NO"
    private fun money(v: Double) = "%.2f".format(Locale.US, v)
    private fun fmtPct(v: Double) = "%.1f%%".format(Locale.US, v * 100.0)
    private fun cfg(c: SignalConfig) = "enter=${"%.2f".format(Locale.US, c.enter)} flip=${"%.2f".format(Locale.US, c.flip)} exit=${"%.2f".format(Locale.US, c.exit)}"
    private fun met(m: LearningMetrics) = "trades=${m.trades} wins=${m.wins} accuracy=${fmtPct(m.accuracy)} pnl=₹${money(m.pnl)} PF=${"%.2f".format(Locale.US, m.profitFactor)} maxDD=₹${money(m.maxDrawdown)}"
}
