package com.suhas.iposentinel

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import org.json.JSONObject
import java.text.NumberFormat
import java.util.Locale

private val Ink = Color(0xFF0F1318)
private val Card = Color(0xFF171D23)
private val Teal = Color(0xFF21D4B4)
private val Danger = Color(0xFFFF6B6B)
private val Muted = Color(0xFF9AA7B3)
private val Amber = Color(0xFFFFC857)

private enum class AppScreen { DASHBOARD, STRATEGIES, SETTINGS }

class MainActivity : ComponentActivity() {
    private val notificationPermissionLauncher =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
            AppAudit.log(
                this,
                "NOTIFICATION_PERMISSION_RESULT",
                JSONObject().put("granted", granted)
            )
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        NotificationHelper.createChannels(this)
        AppAudit.log(this, "APP_STARTED", JSONObject().put("version", BuildConfig.VERSION_NAME))

        if (
            Build.VERSION.SDK_INT >= 33 &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) !=
            PackageManager.PERMISSION_GRANTED
        ) {
            notificationPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
        }

        setContent { IpoSentinelApp() }
    }
}

@Composable
private fun IpoSentinelApp() {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var screen by rememberSaveable { mutableStateOf(AppScreen.DASHBOARD) }
    var liveEnabled by rememberSaveable { mutableStateOf(false) }
    var liveBusy by remember { mutableStateOf(false) }
    var liveMessage by remember { mutableStateOf<String?>(null) }
    var liveMessageColor by remember { mutableStateOf(Muted) }
    var budget by rememberSaveable { mutableFloatStateOf(100_000f) }
    var lastValidation by remember { mutableStateOf<ValidationStatus?>(null) }
    var growwConfigured by remember { mutableStateOf(false) }
    var researchPlan by remember { mutableStateOf<ResearchPlan?>(null) }

    LaunchedEffect(Unit) {
        val api = BackendApi()
        val (_, savedStatus) = api.fetchStatus()
        if (savedStatus != null) {
            growwConfigured = savedStatus.growwConfigured
        }

        val (_, plan) = api.fetchResearchPlan()
        if (plan != null) {
            researchPlan = plan
        }

        val (_, liveState) = api.fetchLiveState()
        if (liveState != null) {
            liveEnabled = liveState.enabled
            budget = liveState.budgetRupees.toFloat()
            if (liveState.enabled && NotificationHelper.notificationsAllowed(context)) {
                ContextCompat.startForegroundService(
                    context,
                    Intent(context, LiveNotificationService::class.java)
                )
            }
        }
    }

    LaunchedEffect(Unit) {
        while (true) {
            delay(60_000L)
            val (result, plan) = BackendApi().fetchResearchPlan()
            if (result.ok && plan != null) {
                researchPlan = plan
                AppAudit.log(
                    context,
                    "RESEARCH_PLAN_UI_SYNC",
                    JSONObject()
                        .put("next_trading_day", plan.nextTradingDay ?: "")
                        .put("candidate_count", plan.nextTradingDayCandidates.size)
                )
            }
        }
    }

    fun requestLiveState(enabled: Boolean) {
        if (liveBusy) return

        if (enabled && !NotificationHelper.notificationsAllowed(context)) {
            liveMessage = "Allow IPO Sentinel notifications before enabling live trading."
            liveMessageColor = Danger
            AppAudit.log(context, "LIVE_ENABLE_BLOCKED_NOTIFICATIONS")
            return
        }

        if (enabled && lastValidation?.liveExecutionReady != true) {
            liveMessage = "Validate Groww + Static IP in Settings before enabling live trading."
            liveMessageColor = Danger
            AppAudit.log(context, "LIVE_ENABLE_BLOCKED_VALIDATION")
            return
        }

        liveBusy = true
        scope.launch {
            AppAudit.log(
                context,
                "LIVE_STATE_REQUEST",
                JSONObject()
                    .put("enabled", enabled)
                    .put("budget_rupees", budget.toInt())
            )
            val (result, state) = BackendApi().setLiveState(enabled, budget.toInt())
            liveBusy = false

            if (result.ok && state != null) {
                liveEnabled = state.enabled
                if (state.enabled) {
                    context.getSharedPreferences("ipo_sentinel_live_events", android.content.Context.MODE_PRIVATE)
                        .edit()
                        .putLong("last_order_event_id", state.eventId)
                        .apply()
                    ContextCompat.startForegroundService(
                        context,
                        Intent(context, LiveNotificationService::class.java)
                    )
                    liveMessage = "Live trading enabled. Order notifications are active."
                    liveMessageColor = Teal
                } else {
                    context.stopService(Intent(context, LiveNotificationService::class.java))
                    liveMessage = "Live trading disabled."
                    liveMessageColor = Muted
                }
                AppAudit.log(
                    context,
                    "LIVE_STATE_ACK",
                    JSONObject()
                        .put("enabled", state.enabled)
                        .put("budget_rupees", state.budgetRupees)
                )
            } else {
                liveMessage = result.error ?: "Live trading state could not be changed."
                liveMessageColor = Danger
                AppAudit.log(
                    context,
                    "LIVE_STATE_FAILED",
                    JSONObject()
                        .put("requested_enabled", enabled)
                        .put("error", result.error ?: "unknown")
                )
            }
        }
    }

    MaterialTheme(
        colorScheme = darkColorScheme(
            primary = Teal,
            secondary = Teal,
            background = Ink,
            surface = Card,
            error = Danger
        )
    ) {
        Scaffold(
            containerColor = Ink,
            bottomBar = {
                NavigationBar(containerColor = Card) {
                    NavigationBarItem(
                        selected = screen == AppScreen.DASHBOARD,
                        onClick = { screen = AppScreen.DASHBOARD },
                        icon = { Text("●") },
                        label = { Text("Dashboard") }
                    )
                    NavigationBarItem(
                        selected = screen == AppScreen.STRATEGIES,
                        onClick = { screen = AppScreen.STRATEGIES },
                        icon = { Text("▲") },
                        label = { Text("Strategies") }
                    )
                    NavigationBarItem(
                        selected = screen == AppScreen.SETTINGS,
                        onClick = { screen = AppScreen.SETTINGS },
                        icon = { Text("⚙") },
                        label = { Text("Settings") }
                    )
                }
            }
        ) { padding ->
            when (screen) {
                AppScreen.DASHBOARD -> DashboardScreen(
                    modifier = Modifier.padding(padding),
                    liveEnabled = liveEnabled,
                    liveBusy = liveBusy,
                    liveMessage = liveMessage,
                    liveMessageColor = liveMessageColor,
                    onLiveEnabledChange = { requested -> requestLiveState(requested) },
                    budget = budget,
                    onBudgetChange = { budget = it },
                    growwConfigured = growwConfigured,
                    validation = lastValidation,
                    researchPlan = researchPlan
                )

                AppScreen.STRATEGIES -> StrategiesScreen(
                    modifier = Modifier.padding(padding)
                )

                AppScreen.SETTINGS -> GrowwSettingsScreen(
                    modifier = Modifier.padding(padding),
                    onConfigurationSaved = { growwConfigured = true },
                    onValidated = {
                        lastValidation = it
                        scope.launch {
                            val (_, refreshedPlan) = BackendApi().fetchResearchPlan()
                            if (refreshedPlan != null) researchPlan = refreshedPlan
                        }
                        if (!it.liveExecutionReady && liveEnabled) {
                            requestLiveState(false)
                        }
                    }
                )
            }
        }
    }
}

@Composable
private fun DashboardScreen(
    modifier: Modifier,
    liveEnabled: Boolean,
    liveBusy: Boolean,
    liveMessage: String?,
    liveMessageColor: Color,
    onLiveEnabledChange: (Boolean) -> Unit,
    budget: Float,
    onBudgetChange: (Float) -> Unit,
    growwConfigured: Boolean,
    validation: ValidationStatus?,
    researchPlan: ResearchPlan?
) {
    Column(
        modifier = modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(18.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp)
    ) {
        Text("IPO Sentinel", fontSize = 30.sp, fontWeight = FontWeight.Bold)
        Text("Listing-day + 30 trading-day intelligence • NSE", color = Muted)

        val readiness = when {
            validation?.liveExecutionReady == true -> "READY"
            growwConfigured -> "NEEDS VALIDATION"
            else -> "NOT CONFIGURED"
        }

        StatusCard(
            title = "Groww API + Static IP",
            primary = readiness,
            secondary = when {
                validation?.liveExecutionReady == true ->
                    "Groww authentication and static-IP checks passed"
                growwConfigured ->
                    "Credentials saved. Validate them from Settings."
                else ->
                    "Add Groww TOTP token, secret and whitelisted static IP in Settings"
            },
            primaryColor = if (validation?.liveExecutionReady == true) Teal else Amber
        )

        val nextDay = researchPlan?.nextTradingDay
        val nextCandidates = researchPlan?.nextTradingDayCandidates.orEmpty()
        val weekCandidates = researchPlan?.weekCandidates.orEmpty()
        val knownCandidates = researchPlan?.allKnownCandidates.orEmpty()
        val researchFailed = researchPlan != null && (
            researchPlan.researchHealth == "FAILED" || !researchPlan.sourceReady
        )

        StatusCard(
            title = "Daily research plan",
            primary = when {
                researchPlan == null -> "NOT SYNCED"
                researchFailed -> "RESEARCH SERVICE FAILED"
                researchPlan.researchHealth == "DEGRADED" -> "DEGRADED"
                else -> "HEALTHY"
            },
            secondary = when {
                researchPlan == null -> "Waiting for the backend research snapshot"
                researchFailed -> researchPlan.errors.joinToString(" • ").ifBlank {
                    "Official IPO source is unavailable; live execution remains blocked."
                }
                else -> "Generated " + (researchPlan.generatedAt ?: "timestamp unavailable") +
                    " • Known " + researchPlan.candidateCount +
                    " • NSE confirmed " + researchPlan.nseIdentityConfirmedCount +
                    " • Groww resolved " + researchPlan.growwResolvedCount +
                    " • Groww pending " + researchPlan.growwPendingCount
            },
            primaryColor = when {
                researchFailed -> Danger
                researchPlan?.researchHealth == "DEGRADED" -> Amber
                researchPlan?.sourceReady == true -> Teal
                else -> Amber
            }
        )

        StatusCard(
            title = "Next trading day",
            primary = when {
                nextDay == null -> "Official calendar not ready"
                researchFailed -> nextDay + " • Research unavailable"
                nextCandidates.isEmpty() -> nextDay + " • No confirmed listing"
                else -> nextDay + " • " + nextCandidates.size + " candidate" +
                    if (nextCandidates.size == 1) "" else "s"
            },
            secondary = when {
                researchFailed -> "Do not interpret this as no listings; the research source failed."
                nextCandidates.isEmpty() && nextDay != null ->
                    "No currently confirmed NSE IPO listings for the selected period"
                else ->
                    nextCandidates.joinToString(" • ") { candidate ->
                        (candidate.symbol ?: "Symbol Pending") + " [" + candidate.lifecycleState + "]"
                    }
            },
            primaryColor = when {
                researchFailed -> Danger
                researchPlan?.calendarReady == true -> Teal
                else -> Amber
            }
        )

        ElevatedCard(colors = CardDefaults.elevatedCardColors(containerColor = Card)) {
            Column(
                Modifier.padding(18.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp)
            ) {
                Text("Next-week IPO research", color = Muted, fontSize = 12.sp)
                val displayCandidates = if (weekCandidates.isNotEmpty()) weekCandidates else knownCandidates
                if (researchFailed) {
                    Text(
                        "Research service failed — candidate list is not authoritative.",
                        color = Danger,
                        fontSize = 12.sp
                    )
                } else if (displayCandidates.isEmpty()) {
                    Text(
                        "No currently confirmed NSE IPO listings for the selected period",
                        color = Muted,
                        fontSize = 12.sp
                    )
                } else {
                    displayCandidates.take(10).forEach { candidate ->
                        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                            Column(Modifier.weight(1f)) {
                                Text(
                                    candidate.symbol ?: "Symbol Pending",
                                    fontWeight = FontWeight.SemiBold
                                )
                                Text(
                                    (candidate.listingDate ?: "Listing date pending") +
                                        " • " + candidate.companyName +
                                        " • " + if (candidate.isSme) "SME" else "Mainboard",
                                    color = Muted,
                                    fontSize = 11.sp
                                )
                                Text(
                                    candidate.lifecycleState +
                                        (candidate.isin?.let { " • ISIN " + it } ?: ""),
                                    color = Muted,
                                    fontSize = 10.sp
                                )
                            }
                            Text(
                                when {
                                    candidate.symbolResolved -> "RESOLVED"
                                    candidate.nseListingConfirmed -> "GROWW PENDING"
                                    candidate.symbol == null -> "RESEARCHING"
                                    else -> "NSE PENDING"
                                },
                                color = if (candidate.symbolResolved) Teal else Amber,
                                fontSize = 9.sp,
                                fontWeight = FontWeight.Bold
                            )
                        }
                    }
                }
                Text(
                    "Live trade gate: final NSE identity + exact Groww NSE/CASH instrument + valid listing-session quote/depth/liquidity/risk checks.",
                    color = Muted,
                    fontSize = 11.sp
                )
            }
        }

        ElevatedCard(colors = CardDefaults.elevatedCardColors(containerColor = Card)) {
            Column(
                Modifier.padding(18.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text("Live auto-trading", fontWeight = FontWeight.SemiBold)
                        Text(
                            when {
                                liveBusy -> "Changing live state…"
                                liveEnabled -> "ARMED — order notifications active"
                                validation?.liveExecutionReady == true -> "READY — switch on when you want live execution"
                                else -> "LOCKED — Groww + static IP validation required"
                            },
                            color = if (liveEnabled) Danger else Muted,
                            fontSize = 13.sp
                        )
                    }
                    Switch(
                        checked = liveEnabled,
                        enabled = !liveBusy,
                        onCheckedChange = onLiveEnabledChange
                    )
                }

                liveMessage?.let {
                    Text(it, color = liveMessageColor, fontSize = 12.sp)
                }

                HorizontalDivider(color = Color(0xFF27313A))

                Text(
                    "Live budget  ₹" + NumberFormat.getNumberInstance(Locale("en", "IN"))
                        .format(budget.toInt()),
                    fontWeight = FontWeight.SemiBold
                )
                Slider(
                    value = budget,
                    enabled = !liveEnabled && !liveBusy,
                    onValueChange = { onBudgetChange((it / 5_000f).toInt() * 5_000f) },
                    valueRange = 10_000f..100_000f
                )
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text("₹10k", color = Muted, fontSize = 12.sp)
                    Text("₹1L", color = Muted, fontSize = 12.sp)
                }
            }
        }

        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            MetricCard("Shadow P&L", "₹0", Modifier.weight(1f))
            MetricCard("Live P&L", if (liveEnabled) "₹0" else "OFF", Modifier.weight(1f))
        }

        StatusCard(
            title = "30-day IPO monitor",
            primary = "0 active listings",
            secondary = "Each new IPO remains under opportunity scan through trading day D30"
        )
        StatusCard(
            title = "Decision engine",
            primary = "WAIT",
            secondary = "No live listing-session evidence yet"
        )
        StatusCard(
            title = "Owned positions",
            primary = "0",
            secondary = "Unrelated Groww portfolio positions are read-only"
        )

        Button(
            modifier = Modifier.fillMaxWidth().height(52.dp),
            colors = ButtonDefaults.buttonColors(containerColor = Danger),
            enabled = !liveBusy,
            onClick = { onLiveEnabledChange(false) }
        ) {
            Text("Emergency Disable", fontWeight = FontWeight.Bold)
        }
    }
}

@Composable
private fun StrategiesScreen(modifier: Modifier) {
    val context = LocalContext.current
    var summary by remember { mutableStateOf<StrategySummary?>(null) }
    var sourceMessage by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    val client = remember { BackendApi() }

    fun refresh() {
        if (busy) return
        busy = true
        scope.launch {
            val (result, value) = client.fetchStrategySummary()
            busy = false
            if (result.ok && value != null) {
                summary = value
                sourceMessage = null
                AppAudit.log(context, "STRATEGY_SUMMARY_SYNCED")
            } else {
                summary = LocalStrategyCatalog.summary()
                sourceMessage = "Showing the built-in strategy catalog. Replay statistics will sync when the trading service is available."
                AppAudit.log(
                    context,
                    "STRATEGY_SUMMARY_FALLBACK",
                    JSONObject().put("error", result.error ?: "unknown")
                )
            }
        }
    }

    LaunchedEffect(Unit) { refresh() }

    Column(
        modifier = modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(18.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp)
    ) {
        Text("Strategies", fontSize = 30.sp, fontWeight = FontWeight.Bold)
        Text(
            "Replay evidence, family rankings and champion promotion status",
            color = Muted,
            fontSize = 13.sp
        )

        if (busy && summary == null) {
            LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
        }

        sourceMessage?.let {
            StatusCard(
                title = "Evidence status",
                primary = "CATALOG AVAILABLE",
                secondary = it,
                primaryColor = Amber
            )
        }

        summary?.let { data ->
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                CompactMetricCard("Total", data.totalStrategyFamilies.toString(), Modifier.weight(1f))
                CompactMetricCard("Tested", data.testedFamilies.toString(), Modifier.weight(1f))
                CompactMetricCard("Champions", data.champions.toString(), Modifier.weight(1f))
            }
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                CompactMetricCard("Challengers", data.challengers.toString(), Modifier.weight(1f))
                CompactMetricCard(
                    "Coverage",
                    if (data.totalStrategyFamilies > 0)
                        ((data.testedFamilies * 100) / data.totalStrategyFamilies).toString() + "%"
                    else "0%",
                    Modifier.weight(1f)
                )
                CompactMetricCard("Research", data.untestedFamilies.toString(), Modifier.weight(1f))
            }

            SettingsSection("Top 5 Working Families") {
                if (data.topFive.isEmpty()) {
                    Text(
                        "No family has enough recorded replay evidence to be called a top performer yet.",
                        color = Muted,
                        fontSize = 13.sp,
                        lineHeight = 19.sp
                    )
                } else {
                    data.topFive.forEachIndexed { index, family ->
                        StrategyFamilyRow(index + 1, family)
                        if (index < data.topFive.lastIndex) {
                            HorizontalDivider(color = Color(0xFF27313A))
                        }
                    }
                }
            }

            SettingsSection("Promotion Pipeline") {
                Text(
                    "CHAMPION requires mature positive evidence after costs. CHALLENGER has sufficient testing but has not passed every promotion gate. RESEARCH is untested or has a small sample.",
                    color = Muted,
                    fontSize = 12.sp,
                    lineHeight = 18.sp
                )
                HorizontalDivider(color = Color(0xFF27313A))
                Text("Champion gate", fontWeight = FontWeight.SemiBold)
                Text(
                    "≥30 trades • positive net expectancy • profit factor ≥1.15 • controlled drawdown • non-negative recent evidence",
                    color = Muted,
                    fontSize = 12.sp
                )
            }

            SettingsSection("Registered Families") {
                data.families.forEachIndexed { index, family ->
                    RegisteredFamilyRow(family)
                    if (index < data.families.lastIndex) {
                        HorizontalDivider(color = Color(0xFF27313A))
                    }
                }
            }

            Text(data.rankingNote, color = Muted, fontSize = 11.sp, lineHeight = 16.sp)

            OutlinedButton(
                onClick = { refresh() },
                enabled = !busy,
                modifier = Modifier.fillMaxWidth()
            ) {
                Text(if (busy) "Refreshing…" else "Refresh Strategy Evidence")
            }
        }
    }
}

@Composable
private fun GrowwSettingsScreen(
    modifier: Modifier,
    onConfigurationSaved: () -> Unit,
    onValidated: (ValidationStatus) -> Unit
) {
    val context = LocalContext.current
    var totpToken by remember { mutableStateOf("") }
    var totpSecret by remember { mutableStateOf("") }
    var staticIp by rememberSaveable { mutableStateOf("") }
    var whitelistConfirmed by rememberSaveable { mutableStateOf(false) }

    var busy by remember { mutableStateOf(false) }
    var exportBusy by remember { mutableStateOf(false) }
    var message by remember { mutableStateOf<String?>(null) }
    var messageColor by remember { mutableStateOf(Muted) }
    var status by remember { mutableStateOf<ConnectionStatus?>(null) }
    var validation by remember { mutableStateOf<ValidationStatus?>(null) }
    var notificationAllowed by remember { mutableStateOf(NotificationHelper.notificationsAllowed(context)) }
    val scope = rememberCoroutineScope()
    val client = remember { BackendApi() }

    fun refreshStatus(showMessage: Boolean) {
        if (busy) return
        busy = true
        scope.launch {
            val (result, value) = client.fetchStatus()
            busy = false
            notificationAllowed = NotificationHelper.notificationsAllowed(context)
            if (result.ok && value != null) {
                status = value
                if (!value.expectedStaticIp.isNullOrBlank()) staticIp = value.expectedStaticIp
                whitelistConfirmed = value.staticIpConfirmed
                if (showMessage) {
                    message = "Settings status refreshed"
                    messageColor = Teal
                }
            } else if (showMessage) {
                message = result.error ?: "Unable to refresh settings"
                messageColor = Danger
            }
        }
    }

    LaunchedEffect(Unit) {
        val (result, value) = client.fetchStatus()
        if (result.ok && value != null) {
            status = value
            if (!value.expectedStaticIp.isNullOrBlank()) staticIp = value.expectedStaticIp
            whitelistConfirmed = value.staticIpConfirmed
        }
    }

    Column(
        modifier = modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(18.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp)
    ) {
        Text("Settings", fontSize = 30.sp, fontWeight = FontWeight.Bold)
        Text(
            "Groww credentials, static-IP validation, notifications and weekly audit export.",
            color = Muted,
            fontSize = 13.sp
        )

        SettingsSection("Order Notifications") {
            CheckRow("Notification permission", notificationAllowed)
            Text(
                "IPO Sentinel requests normal Android notification permission. It does not request access to read notifications from other apps.",
                color = Muted,
                fontSize = 12.sp,
                lineHeight = 18.sp
            )
            if (!notificationAllowed) {
                OutlinedButton(
                    onClick = {
                        val intent = Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).apply {
                            putExtra(Settings.EXTRA_APP_PACKAGE, context.packageName)
                        }
                        context.startActivity(intent)
                    },
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Text("Open Notification Settings")
                }
            } else {
                OutlinedButton(
                    onClick = {
                        NotificationHelper.showOrderEvent(
                            context,
                            OrderLifecycleEvent(
                                id = System.currentTimeMillis(),
                                timestamp = java.time.Instant.now().toString(),
                                eventType = "ORDER_FILLED",
                                symbol = "TEST",
                                side = "BUY",
                                quantity = 1,
                                price = 100.0,
                                orderId = "TEST",
                                message = "Notification test only — no order was placed"
                            )
                        )
                        AppAudit.log(context, "TEST_NOTIFICATION_SENT")
                    },
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Text("Send Test Notification")
                }
            }
        }

        SettingsSection("Groww TOTP") {
            OutlinedTextField(
                value = totpToken,
                onValueChange = { totpToken = it },
                label = { Text("Groww TOTP token / API key") },
                visualTransformation = PasswordVisualTransformation(),
                singleLine = true,
                modifier = Modifier.fillMaxWidth()
            )
            OutlinedTextField(
                value = totpSecret,
                onValueChange = { totpSecret = it },
                label = { Text("Groww TOTP secret") },
                visualTransformation = PasswordVisualTransformation(),
                singleLine = true,
                modifier = Modifier.fillMaxWidth()
            )
            Text(
                "The secret is stored encrypted and is never displayed again after saving.",
                color = Muted,
                fontSize = 12.sp
            )
        }

        SettingsSection("Static IP") {
            OutlinedTextField(
                value = staticIp,
                onValueChange = { staticIp = it.trim() },
                label = { Text("Whitelisted static public IP") },
                placeholder = { Text("203.0.113.10") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Ascii)
            )
            Row(verticalAlignment = Alignment.CenterVertically) {
                Checkbox(
                    checked = whitelistConfirmed,
                    onCheckedChange = { whitelistConfirmed = it }
                )
                Text(
                    "I have whitelisted this IP in Groww",
                    modifier = Modifier.weight(1f)
                )
            }
            Text(
                "This must be the fixed public IP registered in Groww for API order placement.",
                color = Muted,
                fontSize = 12.sp
            )
        }

        Button(
            onClick = {
                if (totpToken.isBlank() || totpSecret.isBlank() || staticIp.isBlank()) {
                    message = "Enter the Groww token, TOTP secret and static IP"
                    messageColor = Danger
                    return@Button
                }
                busy = true
                scope.launch {
                    val result = client.saveGrowwSettings(
                        totpToken = totpToken,
                        totpSecret = totpSecret,
                        expectedStaticIp = staticIp,
                        staticIpConfirmed = whitelistConfirmed
                    )
                    busy = false
                    if (result.ok) {
                        totpToken = ""
                        totpSecret = ""
                        onConfigurationSaved()
                        message = "Groww settings saved securely"
                        messageColor = Teal
                        AppAudit.log(
                            context,
                            "GROWW_SETTINGS_SAVED",
                            JSONObject()
                                .put("static_ip", staticIp)
                                .put("whitelist_confirmed", whitelistConfirmed)
                        )
                        refreshStatus(showMessage = false)
                    } else {
                        message = result.error ?: "Save failed"
                        messageColor = Danger
                        AppAudit.log(
                            context,
                            "GROWW_SETTINGS_SAVE_FAILED",
                            JSONObject().put("error", result.error ?: "unknown")
                        )
                    }
                }
            },
            enabled = !busy,
            modifier = Modifier.fillMaxWidth().height(50.dp)
        ) {
            Text("Save Groww Settings")
        }

        OutlinedButton(
            onClick = {
                busy = true
                scope.launch {
                    val (result, value) = client.validate()
                    busy = false
                    if (result.ok && value != null) {
                        validation = value
                        onValidated(value)
                        message = if (value.liveExecutionReady) {
                            "Validation passed — live execution can be armed"
                        } else {
                            "Validation completed — one or more checks failed"
                        }
                        messageColor = if (value.liveExecutionReady) Teal else Amber
                        AppAudit.log(
                            context,
                            "GROWW_VALIDATION_RESULT",
                            JSONObject()
                                .put("ready", value.liveExecutionReady)
                                .put("auth_ok", value.growwAuthOk)
                                .put("static_ip_matches", value.staticIpMatches)
                                .put("calendar_ready", value.calendarReady)
                                .put("nse_identity_source_ready", value.nseIdentitySourceReady)
                        )
                    } else {
                        message = result.error ?: "Validation failed"
                        messageColor = Danger
                    }
                }
            },
            enabled = !busy,
            modifier = Modifier.fillMaxWidth().height(50.dp)
        ) {
            Text("Validate Groww + Static IP")
        }

        TextButton(
            onClick = { refreshStatus(showMessage = true) },
            enabled = !busy,
            modifier = Modifier.fillMaxWidth()
        ) {
            Text("Refresh Status")
        }

        if (busy) {
            LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
        }

        message?.let {
            Text(it, color = messageColor, fontWeight = FontWeight.SemiBold)
        }

        status?.let {
            SettingsSection("Saved status") {
                CheckRow("Secure credential vault", it.secretStoreReady)
                CheckRow("Groww credentials saved", it.growwConfigured)
                CheckRow("Static IP marked as whitelisted", it.staticIpConfirmed)
            }
        }

        validation?.let {
            SettingsSection("Validation result") {
                CheckRow("Groww TOTP authentication", it.growwAuthOk)
                CheckRow("Static public IP matches", it.staticIpMatches)
                CheckRow("Groww whitelist confirmed", it.staticIpConfirmed)
                CheckRow("Secure credential vault", it.secretStoreReady)
                CheckRow("Official NSE calendar ready", it.calendarReady)
                CheckRow("NSE listing identity source ready", it.nseIdentitySourceReady)
                HorizontalDivider(color = Color(0xFF27313A))
                Text(
                    "Detected static IP: " + (it.detectedEgressIp ?: "Unavailable"),
                    color = Muted,
                    fontSize = 12.sp
                )
                Text(
                    "Whitelisted IP: " + (it.expectedStaticIp ?: "Not configured"),
                    color = Muted,
                    fontSize = 12.sp
                )
                Text(
                    if (it.liveExecutionReady) "LIVE EXECUTION READY" else "LIVE EXECUTION LOCKED",
                    color = if (it.liveExecutionReady) Teal else Danger,
                    fontWeight = FontWeight.Bold
                )
            }
        }

        SettingsSection("Weekly Verification Logs") {
            Text(
                "Exports the last 7 days of app audit events plus backend audit events when available. Broker secrets are excluded.",
                color = Muted,
                fontSize = 12.sp,
                lineHeight = 18.sp
            )
            Button(
                onClick = {
                    if (exportBusy) return@Button
                    exportBusy = true
                    scope.launch {
                        runCatching {
                            val file = AppAudit.exportWeekly(context)
                            AppAudit.shareExport(context, file)
                        }.onFailure { error ->
                            message = "Log export failed: " + (error.message ?: "unknown error")
                            messageColor = Danger
                        }
                        exportBusy = false
                    }
                },
                enabled = !exportBusy,
                modifier = Modifier.fillMaxWidth()
            ) {
                Text(if (exportBusy) "Preparing logs…" else "Export Weekly Logs")
            }
        }

        Text(
            "Security: the TOTP token and secret are not shown after saving. Enter new values and save again if they need to be replaced.",
            color = Muted,
            fontSize = 12.sp
        )
    }
}

@Composable
private fun SettingsSection(title: String, content: @Composable ColumnScope.() -> Unit) {
    ElevatedCard(colors = CardDefaults.elevatedCardColors(containerColor = Card)) {
        Column(
            Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            Text(title, fontWeight = FontWeight.Bold, fontSize = 16.sp)
            content()
        }
    }
}

@Composable
private fun CheckRow(label: String, passed: Boolean) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Text(if (passed) "✓" else "✕", color = if (passed) Teal else Danger, fontWeight = FontWeight.Bold)
        Spacer(Modifier.width(8.dp))
        Text(label, color = Muted)
    }
}

@Composable
private fun CompactMetricCard(label: String, value: String, modifier: Modifier = Modifier) {
    ElevatedCard(
        modifier = modifier,
        colors = CardDefaults.elevatedCardColors(containerColor = Card)
    ) {
        Column(Modifier.padding(12.dp)) {
            Text(label, color = Muted, fontSize = 10.sp)
            Spacer(Modifier.height(4.dp))
            Text(value, fontWeight = FontWeight.Bold, fontSize = 20.sp)
        }
    }
}

@Composable
private fun StrategyFamilyRow(rank: Int, family: StrategyFamilyStats) {
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("#" + rank, color = Teal, fontWeight = FontWeight.Bold, modifier = Modifier.width(32.dp))
            Column(Modifier.weight(1f)) {
                Text(family.name, fontWeight = FontWeight.SemiBold)
                Text(family.phase.replace("_", " "), color = Muted, fontSize = 10.sp)
            }
            StrategyStatusBadge(family.status)
        }
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            StrategyStat("Trades", family.trades.toString())
            StrategyStat("Win", String.format(Locale.US, "%.1f%%", family.winRatePct))
            StrategyStat("Exp.", String.format(Locale.US, "%.1f bps", family.expectancyBps))
            StrategyStat("PF", String.format(Locale.US, "%.2f", family.profitFactor))
        }
        Text(
            "Max DD " + String.format(Locale.US, "%.0f bps", family.maxDrawdownBps) +
                " • Recent " + String.format(Locale.US, "%+.0f bps", family.last20NetBps),
            color = Muted,
            fontSize = 11.sp
        )
    }
}

@Composable
private fun RegisteredFamilyRow(family: StrategyFamilyStats) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Text(family.name, fontWeight = FontWeight.SemiBold, fontSize = 13.sp)
            Text(
                family.phase.replace("_", " ") + " • " + family.trades + " replay trades",
                color = Muted,
                fontSize = 10.sp
            )
        }
        StrategyStatusBadge(family.status)
    }
}

@Composable
private fun StrategyStat(label: String, value: String) {
    Column {
        Text(label, color = Muted, fontSize = 9.sp)
        Text(value, fontWeight = FontWeight.SemiBold, fontSize = 11.sp)
    }
}

@Composable
private fun StrategyStatusBadge(status: String) {
    val color = when (status.uppercase()) {
        "CHAMPION" -> Teal
        "CHALLENGER" -> Amber
        else -> Muted
    }
    Surface(
        color = color.copy(alpha = 0.14f),
        shape = MaterialTheme.shapes.small
    ) {
        Text(
            status,
            color = color,
            fontSize = 9.sp,
            fontWeight = FontWeight.Bold,
            modifier = Modifier.padding(horizontal = 7.dp, vertical = 4.dp)
        )
    }
}

@Composable
private fun MetricCard(label: String, value: String, modifier: Modifier = Modifier) {
    ElevatedCard(modifier = modifier, colors = CardDefaults.elevatedCardColors(containerColor = Card)) {
        Column(Modifier.padding(16.dp)) {
            Text(label, color = Muted, fontSize = 12.sp)
            Spacer(Modifier.height(6.dp))
            Text(value, fontSize = 20.sp, fontWeight = FontWeight.Bold)
        }
    }
}

@Composable
private fun StatusCard(
    title: String,
    primary: String,
    secondary: String,
    primaryColor: Color = Color.Unspecified
) {
    ElevatedCard(colors = CardDefaults.elevatedCardColors(containerColor = Card)) {
        Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(title, color = Muted, fontSize = 12.sp)
            Text(primary, fontSize = 20.sp, fontWeight = FontWeight.Bold, color = primaryColor)
            Text(secondary, color = Muted, fontSize = 13.sp)
        }
    }
}
