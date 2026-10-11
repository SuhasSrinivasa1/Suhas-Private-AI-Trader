package com.multyfi.intraday.mobile

import android.app.Activity
import android.content.Intent
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Bundle
import android.provider.Settings
import android.text.InputType
import android.text.method.PasswordTransformationMethod
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.view.WindowInsets
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.Executors
import kotlin.math.roundToLong

class MainActivity : Activity() {
    private lateinit var repo: AppRepository
    private lateinit var content: LinearLayout
    private lateinit var nav: LinearLayout
    private val navItems = linkedMapOf<String, TextView>()
    private val worker = Executors.newSingleThreadExecutor()
    private var selected = "LIVE"
    private var pendingExport: String? = null
    private val dayFmt = SimpleDateFormat("yyyy-MM-dd", Locale.US)

    private val bg = Color.rgb(250, 247, 252)
    private val card = Color.rgb(238, 233, 241)
    private val cardStrong = Color.rgb(230, 224, 235)
    private val text = Color.rgb(43, 37, 48)
    private val muted = Color.rgb(103, 96, 109)
    private val purple = Color.rgb(104, 76, 177)
    private val purpleSoft = Color.rgb(238, 230, 252)
    private val green = Color.rgb(42, 120, 74)
    private val greenSoft = Color.rgb(227, 244, 234)
    private val red = Color.rgb(177, 58, 52)
    private val redSoft = Color.rgb(251, 231, 230)
    private val amber = Color.rgb(142, 93, 20)
    private val amberSoft = Color.rgb(251, 240, 217)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.statusBarColor = bg
        window.navigationBarColor = bg
        window.decorView.systemUiVisibility = View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR
        repo = AppRepository(this)
        LearningScheduler.scheduleNext(this)
        buildShell()
        showLive()
    }

    override fun onResume() {
        super.onResume()
        if (::content.isInitialized) renderSelected()
    }

    override fun onDestroy() {
        worker.shutdownNow()
        super.onDestroy()
    }

    private fun dp(v: Int): Int = (v * resources.displayMetrics.density).roundToLong().toInt()

    private fun shape(color: Int, radius: Int = 18, strokeColor: Int? = null, strokeWidth: Int = 0): GradientDrawable =
        GradientDrawable().apply {
            setColor(color)
            cornerRadius = dp(radius).toFloat()
            if (strokeColor != null && strokeWidth > 0) setStroke(dp(strokeWidth), strokeColor)
        }

    private fun buildShell() {
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(bg)
            fitsSystemWindows = false
        }

        content = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(20), dp(14), dp(20), dp(28))
        }
        val scroller = ScrollView(this).apply {
            isFillViewport = true
            overScrollMode = View.OVER_SCROLL_NEVER
            addView(content, ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))
        }
        root.addView(scroller, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))

        nav = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER
            setBackgroundColor(Color.rgb(246, 241, 249))
            elevation = dp(10).toFloat()
        }
        listOf("LIVE", "REVIEW", "ACTIVITY", "SETTINGS").forEach { key ->
            val item = TextView(this).apply {
                text = key.lowercase().replaceFirstChar { it.uppercase() }
                gravity = Gravity.CENTER
                textSize = 13f
                setTypeface(Typeface.DEFAULT, Typeface.BOLD)
                setPadding(dp(6), dp(12), dp(6), dp(12))
                setOnClickListener {
                    selected = key
                    renderSelected()
                }
            }
            navItems[key] = item
            nav.addView(item, LinearLayout.LayoutParams(0, dp(48), 1f).apply { setMargins(dp(3), 0, dp(3), 0) })
        }
        root.addView(nav, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))

        root.setOnApplyWindowInsetsListener { v, insets ->
            val topInset = if (android.os.Build.VERSION.SDK_INT >= 30) insets.getInsets(WindowInsets.Type.statusBars()).top else insets.systemWindowInsetTop
            val bottomInset = if (android.os.Build.VERSION.SDK_INT >= 30) insets.getInsets(WindowInsets.Type.navigationBars()).bottom else insets.systemWindowInsetBottom
            v.setPadding(0, topInset, 0, 0)
            nav.setPadding(dp(10), dp(8), dp(10), dp(8) + bottomInset)
            insets
        }
        setContentView(root)
        root.requestApplyInsets()
    }

    private fun updateNav() {
        navItems.forEach { (key, view) ->
            val active = key == selected
            view.setTextColor(if (active) purple else muted)
            view.background = if (active) shape(purpleSoft, 16) else shape(Color.TRANSPARENT, 16)
        }
    }

    private fun renderSelected() {
        when (selected) {
            "REVIEW" -> showReview()
            "ACTIVITY" -> showActivity()
            "SETTINGS" -> showSettings()
            else -> showLive()
        }
    }

    private fun clear() {
        content.removeAllViews()
        updateNav()
    }

    private fun t(s: String, size: Float = 16f, color: Int = text, bold: Boolean = false): TextView = TextView(this).apply {
        this.text = s
        textSize = size
        setTextColor(color)
        setLineSpacing(0f, 1.12f)
        setTypeface(Typeface.create("sans-serif", if (bold) Typeface.BOLD else Typeface.NORMAL))
    }

    private fun spacer(h: Int = 12) = View(this).apply { layoutParams = LinearLayout.LayoutParams(1, dp(h)) }

    private fun screenHeader(title: String, subtitle: String? = null) {
        val row = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL }
        val left = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        left.addView(t(title, 31f, text, true))
        if (!subtitle.isNullOrBlank()) left.addView(t(subtitle, 13f, muted, false).apply { setPadding(0, dp(3), 0, 0) })
        row.addView(left, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        row.addView(pill("PAPER ONLY", purple, purpleSoft))
        content.addView(row)
        content.addView(spacer(18))
    }

    private fun pill(label: String, fg: Int, bgc: Int): TextView = t(label, 11f, fg, true).apply {
        gravity = Gravity.CENTER
        setPadding(dp(10), dp(6), dp(10), dp(6))
        background = shape(bgc, 18)
    }

    private fun cardBox(padding: Int = 18, bgc: Int = card): LinearLayout = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        setPadding(dp(padding), dp(padding), dp(padding), dp(padding))
        background = shape(bgc, 20)
        elevation = dp(1).toFloat()
    }

    private fun addCard(view: View, top: Int = 0, bottom: Int = 12) {
        content.addView(view, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply {
            setMargins(0, dp(top), 0, dp(bottom))
        })
    }

    private fun statusRow(label: String, value: String, ok: Boolean? = null): View {
        val row = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL; setPadding(0, dp(5), 0, dp(5)) }
        row.addView(t(label, 14f, muted), LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        val fg = when (ok) { true -> green; false -> red; null -> text }
        row.addView(t(value, 14f, fg, true))
        return row
    }

    private fun metricCard(label: String, value: String, valueColor: Int = text): View {
        val box = cardBox(14, cardStrong)
        box.addView(t(label, 12f, muted))
        box.addView(t(value, 21f, valueColor, true).apply { setPadding(0, dp(5), 0, 0) })
        return box
    }

    private fun metricRow(metrics: List<Triple<String, String, Int>>) {
        val row = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        metrics.forEachIndexed { i, m ->
            row.addView(metricCard(m.first, m.second, m.third), LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f).apply {
                if (i > 0) leftMargin = dp(8)
            })
        }
        content.addView(row)
        content.addView(spacer(20))
    }

    private fun primaryButton(label: String, onClick: () -> Unit): TextView = t(label, 15f, Color.WHITE, true).apply {
        gravity = Gravity.CENTER
        setPadding(dp(14), dp(16), dp(14), dp(16))
        background = shape(purple, 28)
        setOnClickListener { onClick() }
    }

    private fun secondaryButton(label: String, onClick: () -> Unit): TextView = t(label, 15f, purple, true).apply {
        gravity = Gravity.CENTER
        setPadding(dp(14), dp(15), dp(14), dp(15))
        background = shape(purpleSoft, 28)
        setOnClickListener { onClick() }
    }

    private fun sectionTitle(label: String, detail: String? = null) {
        content.addView(t(label, 19f, text, true))
        if (!detail.isNullOrBlank()) content.addView(t(detail, 13f, muted).apply { setPadding(0, dp(4), 0, 0) })
        content.addView(spacer(10))
    }

    private fun showLive() {
        clear()
        screenHeader("Multyfi Intraday", "Daily-adaptive paper intelligence • V3.0")

        val listener = repo.notificationAccessEnabled()
        val groww = repo.growwValidated()
        val ready = listener && groww
        val s = cardBox(18, if (ready) greenSoft else amberSoft)
        val titleRow = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL }
        titleRow.addView(t(if (ready) "●  SYSTEM READY" else "●  SETUP REQUIRED", 19f, if (ready) green else amber, true), LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        titleRow.addView(pill(if (MarketClock.exchangeState() == "OPEN") "NSE CLOCK OPEN" else "NSE CLOCK CLOSED", if (MarketClock.exchangeState() == "OPEN") green else muted, if (MarketClock.exchangeState() == "OPEN") Color.WHITE else Color.rgb(243, 240, 245)))
        s.addView(titleRow)
        s.addView(spacer(10))
        s.addView(statusRow("Groww API", if (groww) "LIVE" else if (repo.accessToken().isBlank()) "NOT CONFIGURED" else "VALIDATION REQUIRED", if (groww) true else false))
        s.addView(statusRow("Multyfi notification access", if (listener) "ENABLED" else "DISABLED", listener))
        s.addView(statusRow("Static IP", if (repo.staticIpVerified()) "VERIFIED" else if (repo.whitelistIp().isBlank()) "NOT SET" else "NOT VERIFIED", if (repo.whitelistIp().isBlank()) null else repo.staticIpVerified()))
        val feedAge = if (repo.lastFeedTs() <= 0) "WAITING" else "${((System.currentTimeMillis() - repo.lastFeedTs()) / 1000).coerceAtLeast(0)}s ago"
        s.addView(statusRow("Market data", feedAge, if (repo.lastFeedTs() > 0 && System.currentTimeMillis() - repo.lastFeedTs() < 30_000) true else null))
        addCard(s, bottom = 16)

        val m = repo.dayMetrics()
        val capture = repo.captureEfficiency()
        metricRow(listOf(
            Triple("Accuracy", if (m.trades == 0) "—" else "%.1f%%".format(Locale.US, m.accuracy * 100.0), text),
            Triple("Paper P&L", if (m.trades == 0) "₹0" else "₹%.0f".format(Locale.US, m.pnl), if (m.pnl < 0) red else if (m.pnl > 0) green else text),
            Triple("Capture", if (m.trades == 0) "—" else "%.0f%%".format(Locale.US, capture * 100.0), text)
        ))

        val candidates = repo.todayCandidates().sortedBy { it.acceptedTs }
        sectionTitle("${candidates.size} MULTYFI CANDIDATE${if (candidates.size == 1) "" else "S"}", "LONG and SHORT are evaluated symmetrically. New paper risk locks at 14:55 IST.")

        if (candidates.isEmpty()) {
            val empty = cardBox(20)
            empty.addView(t("Waiting for Multyfi candidates", 18f, text, true))
            empty.addView(t("Enable notification access and leave this listener active. Eligible Multyfi notifications will be captured automatically; there are no demo or fabricated trades.", 14f, muted).apply { setPadding(0, dp(8), 0, dp(14)) })
            empty.addView(if (!listener) primaryButton("Grant Multyfi Notification Access") { openNotificationAccess() } else secondaryButton("Open Settings") { selected = "SETTINGS"; showSettings() })
            addCard(empty)
        } else {
            candidates.forEach { c -> addCard(candidateCard(c), bottom = 12) }
        }

        val paper = cardBox(16, purpleSoft)
        paper.addView(t("PAPER AUTO", 16f, purple, true))
        paper.addView(t("Every captured candidate is tracked with live Groww quotes. Entries, reversals, exits, RVOL, rolling sampled VWAP and favorable excursion are stored for replay learning.", 13f, text).apply { setPadding(0, dp(7), 0, 0) })
        paper.addView(t("No broker orders are placed by V3.0.", 13f, purple, true).apply { setPadding(0, dp(8), 0, 0) })
        addCard(paper, top = 6)
    }

    private fun candidateCard(c: CandidateState): View {
        val box = cardBox(17)
        val top = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL }
        val left = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        left.addView(t("${c.symbol} • ${c.source}", 17f, text, true))
        left.addView(t("Accepted ${timeOnly(c.acceptedTs)}", 12f, muted).apply { setPadding(0, dp(3), 0, 0) })
        top.addView(left, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        val signal = when { c.score >= repo.currentConfig().enter -> "LONG"; c.score <= -repo.currentConfig().enter -> "SHORT"; else -> "HOLD" }
        top.addView(pill(signal, when (signal) { "LONG" -> green; "SHORT" -> red; else -> muted }, when (signal) { "LONG" -> greenSoft; "SHORT" -> redSoft; else -> Color.rgb(243, 240, 245) }))
        box.addView(top)
        box.addView(spacer(12))
        val totalPnl = c.realisedPnl + PaperEngine.unrealisedPnl(c)
        box.addView(t("LTP ${if (c.lastLtp > 0) "₹%.2f".format(Locale.US, c.lastLtp) else "—"}  •  Paper ${c.paperSide}  •  P&L ₹%.2f".format(Locale.US, totalPnl), 15f, if (totalPnl < 0) red else if (totalPnl > 0) green else text, true))
        box.addView(t("${c.trend} • score ${"%.2f".format(Locale.US, c.score)} • RVOL ${"%.2f".format(Locale.US, c.rvol)}× • VWAP ${signedPct(c.vwapPct)}", 13f, muted).apply { setPadding(0, dp(7), 0, 0) })
        if (c.status == "SESSION_LOCKED") box.addView(t("SESSION LOCKED", 12f, amber, true).apply { setPadding(0, dp(8), 0, 0) })
        return box
    }

    private fun showReview() {
        clear()
        screenHeader("Daily Learning", "Guarded Champion / Challenger replay")
        val last = repo.lastLearning()
        val sessions = repo.replaySessions().count { it.second.size >= 24 }
        val upToDate = repo.learningUpToDate()
        val statusCard = cardBox(18, when { upToDate && last?.promoted == true -> greenSoft; upToDate -> purpleSoft; else -> amberSoft })
        val headline = when {
            upToDate && last?.promoted == true -> "CHALLENGER PROMOTED"
            upToDate && last?.evaluated == true -> "CHAMPION KEPT"
            repo.evidenceVersion() > repo.lastLearningEvidenceVersion() -> "NEW EVIDENCE PENDING"
            else -> "COLLECTING REPLAY EVIDENCE"
        }
        statusCard.addView(t(headline, 19f, when { headline.contains("PROMOTED") -> green; headline.contains("PENDING") || headline.contains("COLLECTING") -> amber; else -> purple }, true))
        statusCard.addView(t(last?.reason ?: "The learner needs at least 6 completed replay sessions before it can challenge the Champion.", 14f, text).apply { setPadding(0, dp(8), 0, 0) })
        addCard(statusCard, bottom = 16)

        val cfg = repo.currentConfig()
        val champ = cardBox(18)
        champ.addView(t("ACTIVE CHAMPION", 13f, muted, true))
        champ.addView(t("enter ${"%.2f".format(Locale.US, cfg.enter)}   •   flip ${"%.2f".format(Locale.US, cfg.flip)}   •   exit ${"%.2f".format(Locale.US, cfg.exit)}", 20f, text, true).apply { setPadding(0, dp(7), 0, 0) })
        champ.addView(t("Evidence ${repo.evidenceVersion()} • replay sessions $sessions • ${if (upToDate) "learning up to date" else "re-evaluation required"}", 13f, muted).apply { setPadding(0, dp(7), 0, 0) })
        addCard(champ, bottom = 16)

        if (last != null && last.evaluated) {
            sectionTitle("Latest validation", "Training selects the Challenger; chronological validation decides whether it may replace the Champion.")
            val compare = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
            compare.addView(learningMetricBox("CHALLENGER", last.challengerValidation), LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
            compare.addView(learningMetricBox("CHAMPION", last.championValidation), LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f).apply { leftMargin = dp(8) })
            content.addView(compare)
            content.addView(spacer(14))
            val train = cardBox(15, cardStrong)
            train.addView(t("Challenger training", 13f, muted, true))
            train.addView(t("Accuracy ${"%.1f%%".format(Locale.US, last.challengerTrain.accuracy * 100)} • P&L ₹${"%.0f".format(Locale.US, last.challengerTrain.pnl)} • PF ${"%.2f".format(Locale.US, last.challengerTrain.profitFactor)}", 14f, text, true).apply { setPadding(0, dp(5), 0, 0) })
            addCard(train, bottom = 16)
        } else {
            val e = cardBox(16)
            e.addView(t("Evidence requirement", 14f, muted, true))
            e.addView(t("$sessions / 6 replay sessions available", 20f, text, true).apply { setPadding(0, dp(5), 0, 0) })
            e.addView(t("A replay session is created from real captured market ticks for a Multyfi candidate. Demo trades are not used.", 13f, muted).apply { setPadding(0, dp(6), 0, 0) })
            addCard(e, bottom = 16)
        }

        addCard(primaryButton("Run Daily Learning Now") { runLearningAsync() }, bottom = 10)
        addCard(secondaryButton("Download Full Daily Diagnostic (.txt)") { exportDiagnostic() }, bottom = 16)
        content.addView(t("Automatic learning is scheduled after the 15:15 paper force-flat. Every day adds evidence; a parameter change occurs only if the Challenger clears validation gates.", 13f, muted))
    }

    private fun learningMetricBox(title: String, m: LearningMetrics): View {
        val box = cardBox(14)
        box.addView(t(title, 12f, muted, true))
        box.addView(t("${"%.1f%%".format(Locale.US, m.accuracy * 100)}", 23f, text, true).apply { setPadding(0, dp(5), 0, 0) })
        box.addView(t("P&L ₹${"%.0f".format(Locale.US, m.pnl)}", 13f, if (m.pnl < 0) red else green, true).apply { setPadding(0, dp(5), 0, 0) })
        box.addView(t("DD ₹${"%.0f".format(Locale.US, m.maxDrawdown)} • PF ${"%.2f".format(Locale.US, m.profitFactor)}", 12f, muted).apply { setPadding(0, dp(3), 0, 0) })
        return box
    }

    private fun showActivity() {
        clear()
        screenHeader("Activity", "Trades, learning decisions and system events")
        val items = repo.todayActivity().take(150)
        if (items.isEmpty()) {
            val empty = cardBox(20)
            empty.addView(t("No activity yet", 18f, text, true))
            empty.addView(t("Once Multyfi candidates arrive, this screen records captures, market-data issues, paper entries/exits and daily-learning decisions.", 14f, muted).apply { setPadding(0, dp(7), 0, 0) })
            addCard(empty)
            return
        }
        items.forEach { a ->
            val box = cardBox(15)
            val row = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL }
            val fg = when { a.severity == "WARN" -> red; a.type == "LEARNING" -> purple; a.type == "TRADE" -> green; else -> muted }
            row.addView(pill(a.type, fg, when { fg == red -> redSoft; fg == purple -> purpleSoft; fg == green -> greenSoft; else -> Color.rgb(243, 240, 245) }))
            row.addView(t(timeOnly(a.ts), 12f, muted).apply { gravity = Gravity.END }, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
            box.addView(row)
            box.addView(t(a.title, 16f, text, true).apply { setPadding(0, dp(9), 0, 0) })
            box.addView(t(a.detail, 13f, muted).apply { setPadding(0, dp(5), 0, 0) })
            addCard(box, bottom = 10)
        }
    }

    private fun showSettings() {
        clear()
        screenHeader("Settings", "Secure broker configuration and scanner controls")

        val summary = cardBox(18, if (repo.growwValidated() && repo.notificationAccessEnabled()) greenSoft else amberSoft)
        summary.addView(t(if (repo.growwValidated() && repo.notificationAccessEnabled()) "● READY" else "● SETUP REQUIRED", 19f, if (repo.growwValidated() && repo.notificationAccessEnabled()) green else amber, true))
        summary.addView(statusRow("Groww API", if (repo.growwValidated()) "VALIDATED" else "NOT VALIDATED", repo.growwValidated()))
        summary.addView(statusRow("Multyfi access", if (repo.notificationAccessEnabled()) "ENABLED" else "DISABLED", repo.notificationAccessEnabled()))
        summary.addView(statusRow("Static IP", if (repo.staticIpVerified()) "VERIFIED" else "OPTIONAL / NOT VERIFIED", if (repo.whitelistIp().isBlank()) null else repo.staticIpVerified()))
        addCard(summary, bottom = 16)

        sectionTitle("Groww API", "Use either a daily Access Token or API Key + current TOTP. Secrets are encrypted with Android Keystore and never included in diagnostics.")
        val token = editField(if (repo.accessToken().isBlank()) "Groww Access Token" else "Access Token configured — paste only to replace", password = true)
        val apiKey = editField(if (repo.apiKey().isBlank()) "Groww API Key" else "API Key configured — paste only to replace", password = true)
        val totp = editField("Current 6-digit TOTP", numeric = true)
        addCard(token, bottom = 8); addCard(apiKey, bottom = 8); addCard(totp, bottom = 10)
        val growwButtons = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        growwButtons.addView(secondaryButton("Generate token") { generateTokenAsync(apiKey.text.toString(), totp.text.toString()) }, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        growwButtons.addView(primaryButton("Validate Groww") {
            val entered = token.text.toString().trim()
            if (entered.isNotBlank()) repo.saveAccessToken(entered)
            validateGrowwAsync()
        }, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f).apply { leftMargin = dp(8) })
        content.addView(growwButtons)
        content.addView(spacer(20))

        sectionTitle("Static IP", "Optional local verification: the detected public IP must match the value you expect Groww to see.")
        val ip = editField("Whitelisted static IP").apply { setText(repo.whitelistIp()) }
        addCard(ip, bottom = 8)
        val ipCard = cardBox(14)
        ipCard.addView(t("Detected ${repo.detectedIp().ifBlank { "—" }}", 14f, text, true))
        ipCard.addView(t(if (repo.staticIpVerified()) "Matches configured static IP" else "Not verified", 12f, if (repo.staticIpVerified()) green else muted).apply { setPadding(0, dp(4), 0, 0) })
        addCard(ipCard, bottom = 8)
        addCard(secondaryButton("Detect & Verify Static IP") {
            repo.saveWhitelistIp(ip.text.toString())
            detectIpAsync()
        }, bottom = 20)

        sectionTitle("Multyfi candidate access", "The notification listener captures eligible Multyfi alerts and starts paper tracking automatically.")
        val pkg = editField("Optional Multyfi package name filter").apply { setText(repo.sourcePackage()) }
        addCard(pkg, bottom = 8)
        addCard(primaryButton(if (repo.notificationAccessEnabled()) "Open Notification Access" else "Grant Multyfi Notification Access") {
            repo.saveSourcePackage(pkg.text.toString())
            openNotificationAccess()
        }, bottom = 20)

        sectionTitle("Paper risk", "These controls apply to paper simulation and replay only; V3.0 never submits broker orders.")
        val notional = editField("Notional per candidate (₹)", numericDecimal = true).apply { setText("%.0f".format(Locale.US, repo.notional())) }
        val stop = editField("Protective stop (%)", numericDecimal = true).apply { setText("%.2f".format(Locale.US, repo.stopPct())) }
        val trailA = editField("Trail activation (%)", numericDecimal = true).apply { setText("%.2f".format(Locale.US, repo.trailActivationPct())) }
        val trailD = editField("Trail distance (%)", numericDecimal = true).apply { setText("%.2f".format(Locale.US, repo.trailDistancePct())) }
        val hold = editField("Minimum hold (seconds)", numeric = true).apply { setText(repo.minHoldSeconds().toString()) }
        listOf(notional, stop, trailA, trailD, hold).forEach { addCard(it, bottom = 8) }
        addCard(primaryButton("Save Settings") {
            if (token.text.toString().trim().isNotBlank()) repo.saveAccessToken(token.text.toString())
            if (apiKey.text.toString().trim().isNotBlank()) repo.saveApiKey(apiKey.text.toString())
            repo.saveWhitelistIp(ip.text.toString())
            repo.saveSourcePackage(pkg.text.toString())
            repo.saveRiskSettings(notional.text.toString(), stop.text.toString(), trailA.text.toString(), trailD.text.toString(), hold.text.toString())
            toast("Settings saved")
            showSettings()
        }, bottom = 20)

        sectionTitle("Daily diagnostic", "One file contains today's candidates, every paper leg, activity/errors, learning comparison and raw captured market ticks. Secrets are excluded.")
        addCard(secondaryButton("Download Full Daily Diagnostic (.txt)") { exportDiagnostic() })
    }

    private fun editField(hintText: String, password: Boolean = false, numeric: Boolean = false, numericDecimal: Boolean = false): EditText = EditText(this).apply {
        hint = hintText
        textSize = 15f
        setTextColor(text)
        setHintTextColor(muted)
        setPadding(dp(16), dp(13), dp(16), dp(13))
        background = shape(Color.WHITE, 14, Color.rgb(219, 211, 225), 1)
        singleLine = true
        inputType = when {
            numericDecimal -> InputType.TYPE_CLASS_NUMBER or InputType.TYPE_NUMBER_FLAG_DECIMAL
            numeric -> InputType.TYPE_CLASS_NUMBER
            password -> InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
            else -> InputType.TYPE_CLASS_TEXT
        }
        if (password) transformationMethod = PasswordTransformationMethod.getInstance()
    }

    private fun openNotificationAccess() {
        startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
    }

    private fun validateGrowwAsync() {
        val token = repo.accessToken()
        if (token.isBlank()) { toast("Paste or generate a Groww access token first"); return }
        toast("Validating Groww…")
        worker.execute {
            val ok = GrowwClient.validateAccessToken(token)
            runOnUiThread {
                if (ok) {
                    repo.markGrowwValidated()
                    repo.logActivity("SYSTEM", "Groww API validated", "Live quote authentication succeeded.")
                    toast("Groww API validated")
                } else {
                    repo.clearGrowwValidation()
                    repo.logActivity("SYSTEM", "Groww validation failed", "The access token could not fetch a live quote.", "WARN")
                    toast("Groww validation failed — check the token")
                }
                showSettings()
            }
        }
    }

    private fun generateTokenAsync(apiKeyEntered: String, totp: String) {
        if (apiKeyEntered.isNotBlank()) repo.saveApiKey(apiKeyEntered)
        val key = repo.apiKey()
        if (key.isBlank()) { toast("Enter the Groww API key first"); return }
        if (!totp.trim().matches(Regex("\\d{6}"))) { toast("Enter the current 6-digit TOTP"); return }
        toast("Generating Groww token…")
        worker.execute {
            runCatching { GrowwClient.generateAccessToken(key, totp.trim()) }
                .onSuccess { access ->
                    repo.saveAccessToken(access)
                    val ok = GrowwClient.validateAccessToken(access)
                    if (ok) repo.markGrowwValidated()
                    runOnUiThread { toast(if (ok) "Token generated and validated" else "Token generated; validation failed"); showSettings() }
                }
                .onFailure { e -> runOnUiThread { toast(e.message ?: "Groww token generation failed") } }
        }
    }

    private fun detectIpAsync() {
        toast("Detecting public IP…")
        worker.execute {
            runCatching { GrowwClient.detectPublicIp() }
                .onSuccess { value ->
                    repo.saveDetectedIp(value)
                    repo.logActivity("SYSTEM", "Static IP checked", "Detected public IP $value; match=${repo.staticIpVerified()}.")
                    runOnUiThread { toast(if (repo.staticIpVerified()) "Static IP verified" else "Detected $value — it does not match the configured IP"); showSettings() }
                }
                .onFailure { e -> runOnUiThread { toast(e.message ?: "IP detection failed") } }
        }
    }

    private fun runLearningAsync() {
        toast("Running chronological replay…")
        worker.execute {
            val result = ReplayEngine().learn(repo)
            if (result.promoted) repo.saveConfig(result.championAfter)
            repo.recordLearning(result)
            runOnUiThread { toast(if (result.promoted) "Challenger promoted" else if (result.evaluated) "Champion kept" else "More replay sessions required"); showReview() }
        }
    }

    private fun exportDiagnostic() {
        pendingExport = DiagnosticExporter.build(repo)
        val name = "Multyfi_Diagnostic_${dayFmt.format(Date())}.txt"
        val i = Intent(Intent.ACTION_CREATE_DOCUMENT).apply {
            addCategory(Intent.CATEGORY_OPENABLE)
            type = "text/plain"
            putExtra(Intent.EXTRA_TITLE, name)
        }
        startActivityForResult(i, 7001)
    }

    @Deprecated("Deprecated in Java")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == 7001 && resultCode == RESULT_OK && data?.data != null) {
            runCatching {
                contentResolver.openOutputStream(data.data!!)?.use { it.write((pendingExport ?: "").toByteArray(Charsets.UTF_8)) }
            }.onSuccess { toast("Daily diagnostic saved") }
                .onFailure { toast("Could not save diagnostic") }
            pendingExport = null
        }
    }

    private fun toast(s: String) = Toast.makeText(this, s, Toast.LENGTH_LONG).show()
    private fun timeOnly(ts: Long): String = SimpleDateFormat("HH:mm:ss", Locale.US).format(Date(ts))
    private fun signedPct(v: Double): String = (if (v >= 0) "+" else "") + "%.2f%%".format(Locale.US, v)
}
