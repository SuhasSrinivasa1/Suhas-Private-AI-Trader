from pathlib import Path

base = Path('Multyfi_Intraday_Mobile_V3_0')
src = base / 'app/src/main/java/com/multyfi/intraday/mobile'

# Version bump. Keep minSdk 26 for Android 8.0+ devices such as the LG G7 ThinQ.
p = base / 'app/build.gradle.kts'
s = p.read_text()
if 'versionCode = 308' not in s or 'versionName = "3.0.8"' not in s:
    raise SystemExit('Expected transformed V3.0.8 build config was not found')
s = s.replace('versionCode = 308', 'versionCode = 309', 1)
s = s.replace('versionName = "3.0.8"', 'versionName = "3.0.9"', 1)
p.write_text(s)

# Persist feed-health state so UI, scanner and diagnostics agree.
p = src / 'AppRepository.kt'
s = p.read_text()
hook = '    fun markFeed() { prefs.edit().putLong("last_feed_ts", System.currentTimeMillis()).apply() }\n'
if hook not in s:
    raise SystemExit('AppRepository feed hook not found')
extra = '''    fun markFeedDegraded(kind: String, detail: String, backoffUntil: Long) {
        prefs.edit()
            .putBoolean("feed_degraded", true)
            .putString("feed_issue_kind", kind)
            .putString("feed_issue_detail", detail.take(500))
            .putLong("feed_degraded_ts", System.currentTimeMillis())
            .putLong("feed_backoff_until", backoffUntil)
            .apply()
    }

    fun markFeedRecovered(entryResumeTs: Long) {
        prefs.edit()
            .putBoolean("feed_degraded", false)
            .putString("feed_issue_kind", "")
            .putString("feed_issue_detail", "")
            .putLong("feed_recovered_ts", System.currentTimeMillis())
            .putLong("feed_backoff_until", 0L)
            .putLong("feed_entry_resume_ts", entryResumeTs)
            .apply()
    }

    fun feedDegraded(): Boolean = prefs.getBoolean("feed_degraded", false)
    fun feedIssueKind(): String = prefs.getString("feed_issue_kind", "") ?: ""
    fun feedIssueDetail(): String = prefs.getString("feed_issue_detail", "") ?: ""
    fun feedBackoffUntil(): Long = prefs.getLong("feed_backoff_until", 0L)
    fun feedEntryResumeTs(): Long = prefs.getLong("feed_entry_resume_ts", 0L)
'''
s = s.replace(hook, hook + extra, 1)
p.write_text(s)

# Connectivity guard around V3.0.8 adaptive quote loop.
p = src / 'MultyfiNotificationService.kt'
s = p.read_text()
hook = '    @Volatile private var quoteCursor = 0\n'
if hook not in s:
    raise SystemExit('V3.0.8 quoteCursor hook not found')
state = '''    @Volatile private var feedFailureStreak = 0
    @Volatile private var feedSuccessStreak = 0
    @Volatile private var feedDegraded = false
    @Volatile private var backoffUntilMs = 0L
    @Volatile private var entryResumeAfterMs = 0L
'''
s = s.replace(hook, hook + state, 1)

start = s.index('    private fun safePoll() {')
end = s.index('    private fun throttledLog(', start)
replacement = r'''    private fun safePoll() {
        runCatching {
            repo.markListenerHeartbeat()
            val nowMs = System.currentTimeMillis()
            if (repo.feedDegraded()) feedDegraded = true
            val pauseUntil = maxOf(backoffUntilMs, repo.feedBackoffUntil())
            if (nowMs < pauseUntil) return

            val validSymbols = catalog.cachedSymbols().ifEmpty {
                refreshCatalogAndSanitize(force = false) ?: return
            }
            if (validSymbols.size < 500) return

            if (MarketClock.shouldForceFlat()) {
                repo.todayCandidates()
                    .filter { it.symbol.uppercase(Locale.US) in validSymbols }
                    .forEach { c ->
                        val flat = PaperEngine.forceFlat(repo, c)
                        LiveTradeEngine.sync(repo, c, flat)
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

            val active = repo.todayCandidates()
                .filter { it.status != "SESSION_LOCKED" }
                .filter { it.symbol.uppercase(Locale.US) in validSymbols }
            if (active.isEmpty()) return

            val idx = Math.floorMod(quoteCursor, active.size)
            val c = active[idx]
            quoteCursor = if (quoteCursor == Int.MAX_VALUE) 0 else quoteCursor + 1

            runCatching {
                val q = GrowwClient.quote(token, c.symbol)
                repo.appendTick(c.id, q)
                noteQuoteSuccess()

                val ticks = repo.ticks(c.id).takeLast(180)
                val gateUntil = maxOf(entryResumeAfterMs, repo.feedEntryResumeTs())
                val blockFreshEntry = feedDegraded || repo.feedDegraded() || System.currentTimeMillis() < gateUntil
                val updated = if (blockFreshEntry && c.paperSide == "FLAT") {
                    val f = SignalMath.latest(ticks)
                    c.copy(
                        lastLtp = f.price,
                        lastUpdatedTs = f.ts,
                        score = f.score,
                        rvol = f.rvol,
                        vwapPct = f.vwapPct,
                        trend = f.trend
                    )
                } else {
                    PaperEngine.onQuote(repo, c, ticks)
                }
                LiveTradeEngine.sync(repo, c, updated)
                repo.saveCandidate(updated)
            }.onFailure { e ->
                noteQuoteFailure(c.symbol, e)
            }
        }.onFailure { e ->
            throttledLog("loop", "Scanner loop error", e.message ?: "Unknown scanner error", "WARN")
        }
    }

    private fun classifyFeedError(e: Throwable): String {
        val m = (e.message ?: e.javaClass.simpleName).lowercase(Locale.US)
        return when {
            "unable to resolve host" in m || "no address associated" in m || "unknownhost" in m -> "DNS"
            "timeout" in m || "timed out" in m || "sockettimeoutexception" in m -> "TIMEOUT"
            "http 429" in m || ("rate" in m && "limit" in m) -> "RATE LIMIT"
            "http 401" in m || "http 403" in m || "unauthorized" in m || "forbidden" in m -> "AUTH"
            "http 4" in m || "bad request" in m -> "API"
            "connection abort" in m || "failed to connect" in m || "connection reset" in m -> "NETWORK"
            else -> "NETWORK"
        }
    }

    private fun retryDelayMs(kind: String, streak: Int): Long = when (kind) {
        "RATE LIMIT" -> 60_000L
        "AUTH" -> 30_000L
        "DNS" -> when { streak >= 5 -> 20_000L; streak >= 3 -> 10_000L; else -> 5_000L }
        "TIMEOUT" -> when { streak >= 5 -> 15_000L; streak >= 3 -> 7_000L; else -> 3_000L }
        "API" -> 5_000L
        else -> when { streak >= 5 -> 15_000L; streak >= 3 -> 7_000L; else -> 2_000L }
    }

    private fun noteQuoteFailure(symbol: String, e: Throwable) {
        val now = System.currentTimeMillis()
        feedSuccessStreak = 0
        feedFailureStreak += 1
        val kind = classifyFeedError(e)
        val delay = retryDelayMs(kind, feedFailureStreak)
        backoffUntilMs = now + delay
        val detail = e.message ?: "Groww quote failed"

        if (feedFailureStreak >= 2 && !feedDegraded) {
            feedDegraded = true
            repo.markFeedDegraded(kind, detail, backoffUntilMs)
            repo.logActivity(
                "SYSTEM",
                "FEED DEGRADED • $kind",
                "${feedFailureStreak} consecutive Groww quote failures. New entries are paused. Existing positions are still managed whenever fresh quotes arrive. Retry backoff ${delay / 1000}s. Last symbol: $symbol • $detail",
                "WARN"
            )
        } else if (feedDegraded) {
            repo.markFeedDegraded(kind, detail, backoffUntilMs)
            throttledLog(
                "feed_degraded",
                "Feed still degraded • $kind",
                "New entries remain paused; retrying with controlled backoff. Last symbol: $symbol • $detail",
                "WARN"
            )
        }
    }

    private fun noteQuoteSuccess() {
        val wasDegraded = feedDegraded || repo.feedDegraded()
        if (!wasDegraded) {
            feedFailureStreak = 0
            feedSuccessStreak = 0
            return
        }

        feedSuccessStreak += 1
        if (feedSuccessStreak < 3) return

        val now = System.currentTimeMillis()
        feedDegraded = false
        feedFailureStreak = 0
        feedSuccessStreak = 0
        backoffUntilMs = 0L
        entryResumeAfterMs = now + 30_000L
        repo.markFeedRecovered(entryResumeAfterMs)
        repo.logActivity(
            "SYSTEM",
            "FEED RECOVERED",
            "Three consecutive fresh Groww quotes succeeded. Existing positions continue normally; fresh entries wait for a 30-second clean-data warm-up.",
            "INFO"
        )
    }

'''
s = s[:start] + replacement + s[end:]
p.write_text(s)

# Live UI and Settings: make connectivity state explicit without changing trading thresholds.
p = src / 'MainActivity.kt'
s = p.read_text()
s = s.replace(
    'screenHeader("Multyfi Intraday", "Daily-adaptive paper intelligence • V3.0.8")',
    'screenHeader("Multyfi Intraday", "Daily-adaptive paper intelligence • V3.0.9")',
    1
)
old = '        val ready = listener && groww\n'
new = '        val exchangeOpen = MarketClock.exchangeState() == "OPEN"\n        val feedDegradedNow = exchangeOpen && repo.feedDegraded()\n        val ready = listener && groww && !feedDegradedNow\n'
if old not in s:
    raise SystemExit('MainActivity ready hook not found')
s = s.replace(old, new, 1)
old = '        titleRow.addView(t(if (ready) "●  SYSTEM READY" else "●  SETUP REQUIRED", 19f, if (ready) green else amber, true), LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))\n'
new = '        titleRow.addView(t(if (feedDegradedNow) "●  FEED DEGRADED" else if (ready) "●  SYSTEM READY" else "●  SETUP REQUIRED", 19f, if (feedDegradedNow) red else if (ready) green else amber, true), LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))\n'
if old not in s:
    raise SystemExit('MainActivity title hook not found')
s = s.replace(old, new, 1)
old = '''        val feedAge = if (repo.lastFeedTs() <= 0) "WAITING" else "${((System.currentTimeMillis() - repo.lastFeedTs()) / 1000).coerceAtLeast(0)}s ago"
        s.addView(statusRow("Market data", feedAge, if (repo.lastFeedTs() > 0 && System.currentTimeMillis() - repo.lastFeedTs() < 30_000) true else null))
'''
new = '''        val feedNow = System.currentTimeMillis()
        val lastFeed = repo.lastFeedTs()
        val warmupUntil = repo.feedEntryResumeTs()
        val feedAgeSec = if (lastFeed <= 0L) Long.MAX_VALUE else ((feedNow - lastFeed) / 1000L).coerceAtLeast(0L)
        val feedLabel = when {
            !exchangeOpen && lastFeed > 0L -> "SESSION CLOSED • final tick recorded"
            repo.feedDegraded() -> "DEGRADED • ${repo.feedIssueKind().ifBlank { "NETWORK" }}"
            feedNow < warmupUntil -> "RECOVERED • warm-up ${((warmupUntil - feedNow + 999L) / 1000L)}s"
            lastFeed <= 0L -> "WAITING"
            else -> "${feedAgeSec}s ago"
        }
        val feedOk: Boolean? = when {
            repo.feedDegraded() -> false
            !exchangeOpen -> null
            feedNow < warmupUntil -> null
            lastFeed > 0L && feedNow - lastFeed < 30_000L -> true
            else -> null
        }
        s.addView(statusRow("Market data", feedLabel, feedOk))
'''
if old not in s:
    raise SystemExit('MainActivity feed row hook not found')
s = s.replace(old, new, 1)

hook = '        addCard(cadenceCard, bottom = 20)\n\n'
if hook not in s:
    raise SystemExit('MainActivity cadence card hook not found')
extra = '''        val resilienceCard = cardBox(16, purpleSoft)
        resilienceCard.addView(t("FEED RESILIENCE — AUTO", 14f, purple, true))
        resilienceCard.addView(t("DNS failures, timeouts, rate limits and other network failures are classified separately. After repeated failures the app marks FEED DEGRADED, pauses fresh entries, retries with backoff, and requires three fresh quotes plus a 30-second warm-up before new entries resume. Existing positions are still managed whenever fresh quotes arrive.", 13f, text).apply { setPadding(0, dp(6), 0, 0) })
        addCard(resilienceCard, bottom = 20)

'''
s = s.replace(hook, hook + extra, 1)
p.write_text(s)

# Diagnostic header and feed-health details.
p = src / 'DiagnosticExporter.kt'
s = p.read_text()
s = s.replace('V3.0.8 — FULL DAILY DIAGNOSTIC', 'V3.0.9 — FULL DAILY DIAGNOSTIC', 1)
s = s.replace('App version: 3.0.8', 'App version: 3.0.9', 1)
hook = '            appendLine("Groww documented Live Data limit: 10 requests/sec, 300/min")\n'
if hook not in s:
    raise SystemExit('Diagnostic polling hook not found')
extra = '''            appendLine("Feed health: ${if (repo.feedDegraded()) "DEGRADED" else "HEALTHY/RECOVERING"}")
            appendLine("Feed issue kind: ${repo.feedIssueKind().ifBlank { "NONE" }}")
            appendLine("Feed issue detail: ${repo.feedIssueDetail().ifBlank { "NONE" }}")
            appendLine("New-entry warm-up remaining seconds: ${((repo.feedEntryResumeTs() - System.currentTimeMillis()).coerceAtLeast(0L) / 1000L)}")
'''
s = s.replace(hook, hook + extra, 1)
p.write_text(s)

# Build-time assertions.
assert 'versionCode = 309' in (base / 'app/build.gradle.kts').read_text()
assert 'versionName = "3.0.9"' in (base / 'app/build.gradle.kts').read_text()
assert 'minSdk = 26' in (base / 'app/build.gradle.kts').read_text()
assert 'FEED DEGRADED' in (src / 'MultyfiNotificationService.kt').read_text()
assert 'FEED RECOVERED' in (src / 'MultyfiNotificationService.kt').read_text()
assert 'entryResumeAfterMs = now + 30_000L' in (src / 'MultyfiNotificationService.kt').read_text()
assert 'SESSION CLOSED • final tick recorded' in (src / 'MainActivity.kt').read_text()
assert 'FEED RESILIENCE — AUTO' in (src / 'MainActivity.kt').read_text()
assert 'MULTYFI INTRADAY MOBILE V3.0.9' in (src / 'DiagnosticExporter.kt').read_text()
