package com.multyfi.intraday.mobile

import android.app.Notification
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import java.util.Locale
import java.util.concurrent.Executors
import java.util.concurrent.ScheduledExecutorService
import java.util.concurrent.TimeUnit

class MultyfiNotificationService : NotificationListenerService() {
    private lateinit var repo: AppRepository
    private lateinit var catalog: GrowwInstrumentCatalog
    private lateinit var sanitizer: CandidateSanitizer
    private var executor: ScheduledExecutorService? = null
    private val errorTimestamps = mutableMapOf<String, Long>()
    @Volatile private var lastCatalogRefreshAttempt = 0L

    override fun onCreate() {
        super.onCreate()
        repo = AppRepository(this)
        catalog = GrowwInstrumentCatalog(this)
        sanitizer = CandidateSanitizer(this)
    }

    override fun onListenerConnected() {
        super.onListenerConnected()
        repo.markListenerHeartbeat()
        repo.logActivity("SYSTEM", "Multyfi access enabled", "Notification listener connected and candidate capture is active.")
        startLoop()
        executor?.execute { refreshCatalogAndSanitize(force = false) }
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

        processCandidateText(combined, n.packageName, allowRefresh = true)
    }

    private fun processCandidateText(combined: String, packageName: String, allowRefresh: Boolean) {
        val symbols = catalog.cachedSymbols()
        if (symbols.size >= 500) {
            val symbol = catalog.matchNotification(combined, symbols)
            if (symbol != null) {
                acceptValidatedCandidate(symbol, combined, packageName)
                return
            }
        }

        if (allowRefresh) {
            val now = System.currentTimeMillis()
            if (now - lastCatalogRefreshAttempt >= 60_000L) {
                lastCatalogRefreshAttempt = now
                executor?.execute {
                    val refreshed = runCatching { catalog.loadOrRefresh(force = true) }
                        .onFailure { e -> throttledLog("catalog", "Groww instrument catalog unavailable", e.message ?: "Instrument catalog refresh failed", "WARN") }
                        .getOrNull()
                    if (refreshed != null && refreshed.size >= 500) {
                        sanitize(refreshed)
                        val retry = catalog.matchNotification(combined, refreshed)
                        if (retry != null) acceptValidatedCandidate(retry, combined, packageName)
                        else throttledLog("parse", "Candidate rejected", "Multyfi notification contained no valid NSE CASH trading symbol. No candidate was created.")
                    }
                }
                return
            }
        }

        throttledLog("parse", "Candidate rejected", "Multyfi notification contained no valid NSE CASH trading symbol. No candidate was created.")
    }

    private fun acceptValidatedCandidate(symbol: String, combined: String, packageName: String) {
        val source = when {
            combined.contains("PAID", true) && combined.contains("INTRADAY", true) -> "PAID INTRADAY"
            combined.contains("FREE", true) -> "FREE EQUITY"
            else -> "MULTYFI"
        }
        repo.acceptCandidate(symbol.uppercase(Locale.US), source, combined, packageName)
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

    private fun refreshCatalogAndSanitize(force: Boolean): Set<String>? {
        lastCatalogRefreshAttempt = System.currentTimeMillis()
        return runCatching { catalog.loadOrRefresh(force) }
            .onSuccess { symbols ->
                sanitize(symbols)
            }
            .onFailure { e ->
                throttledLog("catalog", "Groww instrument catalog unavailable", e.message ?: "Instrument catalog refresh failed", "WARN")
            }
            .getOrNull()
    }

    private fun sanitize(symbols: Set<String>) {
        val result = sanitizer.purgeToday(symbols)
        if (result.removedCandidates > 0) {
            repo.logActivity(
                "SYSTEM",
                "Invalid candidates purged",
                "Removed ${result.removedCandidates} non-instrument candidate(s), ${result.removedTrades} linked trade event(s) and ${result.removedTicks} tick file(s). Today's learning state was invalidated if affected.",
                "INFO"
            )
        }
    }

    private fun safePoll() {
        runCatching {
            repo.markListenerHeartbeat()
            val validSymbols = catalog.cachedSymbols().ifEmpty {
                refreshCatalogAndSanitize(force = false) ?: return
            }
            if (validSymbols.size < 500) return

            if (MarketClock.shouldForceFlat()) {
                repo.todayCandidates()
                    .filter { it.symbol.uppercase(Locale.US) in validSymbols }
                    .forEach { c ->
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

            repo.todayCandidates()
                .filter { it.status != "SESSION_LOCKED" }
                .filter { it.symbol.uppercase(Locale.US) in validSymbols }
                .forEach { c ->
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
