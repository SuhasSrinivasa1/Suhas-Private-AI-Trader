package com.multyfi.intraday.mobile

import android.app.Notification
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import java.util.concurrent.Executors
import java.util.concurrent.ScheduledExecutorService
import java.util.concurrent.TimeUnit

class MultyfiNotificationService : NotificationListenerService() {
    private lateinit var repo: AppRepository
    private var executor: ScheduledExecutorService? = null
    private val errorTimestamps = mutableMapOf<String, Long>()

    override fun onCreate() {
        super.onCreate()
        repo = AppRepository(this)
    }

    override fun onListenerConnected() {
        super.onListenerConnected()
        repo.markListenerHeartbeat()
        repo.logActivity("SYSTEM", "Multyfi access enabled", "Notification listener connected and candidate capture is active.")
        startLoop()
    }

    override fun onListenerDisconnected() {
        repo.logActivity("SYSTEM", "Multyfi listener disconnected", "Android disconnected the notification listener.", "WARN")
        stopLoop()
        super.onListenerDisconnected()
    }

    override fun onDestroy() {
        stopLoop()
        super.onDestroy()
    }

    override fun onNotificationPosted(sbn: StatusBarNotification?) {
        val n = sbn ?: return
        repo.markListenerHeartbeat()
        val extras = n.notification.extras
        val title = extras.getCharSequence(Notification.EXTRA_TITLE)?.toString().orEmpty()
        val text = extras.getCharSequence(Notification.EXTRA_TEXT)?.toString().orEmpty()
        val big = extras.getCharSequence(Notification.EXTRA_BIG_TEXT)?.toString().orEmpty()
        val combined = listOf(title, text, big).filter { it.isNotBlank() }.distinct().joinToString(" • ")
        if (combined.isBlank()) return

        val configuredPkg = repo.sourcePackage()
        val packageMatches = configuredPkg.isNotBlank() && n.packageName == configuredPkg
        val looksMultyfi = n.packageName.contains("multyfi", true) || combined.contains("multyfi", true)
        if (!packageMatches && !looksMultyfi) return

        val symbol = extractSymbol(combined) ?: run {
            throttledLog("parse", "Candidate parse skipped", "Multyfi notification received but no NSE-style symbol could be identified: ${combined.take(220)}")
            return
        }
        val source = when {
            combined.contains("PAID", true) && combined.contains("INTRADAY", true) -> "PAID INTRADAY"
            combined.contains("FREE", true) -> "FREE EQUITY"
            else -> "MULTYFI"
        }
        repo.acceptCandidate(symbol, source, combined, n.packageName)
    }

    private fun extractSymbol(text: String): String? {
        val excluded = setOf(
            "MULTYFI", "BUY", "SELL", "LONG", "SHORT", "HOLD", "NSE", "BSE", "FREE", "PAID",
            "INTRADAY", "EQUITY", "ALERT", "CALL", "LTP", "TARGET", "STOP", "LOSS", "ENTRY", "EXIT",
            "LIVE", "OPEN", "CLOSE", "PAPER", "READY", "NEW", "SIGNAL"
        )
        val preferred = Regex("(?:NSE[:_\\- ]+)?([A-Z][A-Z0-9&.-]{1,14})").findAll(text.uppercase())
            .map { it.groupValues[1] }
            .filter { it !in excluded && it.any(Char::isLetter) }
            .filterNot { it.matches(Regex("\\d+")) }
            .toList()
        return preferred.firstOrNull()
    }

    private fun startLoop() {
        if (executor?.isShutdown == false) return
        executor = Executors.newSingleThreadScheduledExecutor().also { ex ->
            ex.scheduleWithFixedDelay({ safePoll() }, 1, 5, TimeUnit.SECONDS)
        }
    }

    private fun stopLoop() {
        executor?.shutdownNow()
        executor = null
    }

    private fun safePoll() {
        runCatching {
            repo.markListenerHeartbeat()
            if (MarketClock.shouldForceFlat()) {
                repo.todayCandidates().forEach { c ->
                    val flat = PaperEngine.forceFlat(repo, c)
                    if (flat != c) repo.saveCandidate(flat)
                }
                val n = MarketClock.now()
                if (n.hour >= 15 && n.minute >= 20 && !repo.learningUpToDate()) {
                    val r = ReplayEngine().learn(repo)
                    if (r.promoted) repo.saveConfig(r.championAfter)
                    repo.recordLearning(r)
                }
                return
            }
            if (!MarketClock.isTrackingWindow()) return
            val token = repo.accessToken()
            if (token.isBlank()) return
            repo.todayCandidates().filter { it.status != "SESSION_LOCKED" }.forEach { c ->
                runCatching {
                    val q = GrowwClient.quote(token, c.symbol)
                    repo.appendTick(c.id, q)
                    val updated = PaperEngine.onQuote(repo, c, repo.ticks(c.id).takeLast(180))
                    repo.saveCandidate(updated)
                }.onFailure { e ->
                    throttledLog("quote_${c.symbol}", "Market data error • ${c.symbol}", e.message ?: "Groww quote failed", "WARN")
                }
            }
        }.onFailure { e -> throttledLog("loop", "Scanner loop error", e.message ?: "Unknown scanner error", "WARN") }
    }

    private fun throttledLog(key: String, title: String, detail: String, severity: String = "INFO") {
        val now = System.currentTimeMillis()
        val last = errorTimestamps[key] ?: 0L
        if (now - last >= 60_000L) {
            errorTimestamps[key] = now
            repo.logActivity("SYSTEM", title, detail, severity)
        }
    }
}
