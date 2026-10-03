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
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import kotlinx.coroutines.launch
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
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        NotificationHelper.createChannels(this)

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
    var screen by rememberSaveable { mutableStateOf(AppScreen.DASHBOARD) }
    var liveEnabled by rememberSaveable { mutableStateOf(false) }
    var budget by rememberSaveable { mutableFloatStateOf(100_000f) }
    var lastValidation by remember { mutableStateOf<ValidationStatus?>(null) }
    var growwConfigured by remember { mutableStateOf(false) }

    LaunchedEffect(liveEnabled) {
        val serviceIntent = Intent(context, TradeEventService::class.java)
        if (liveEnabled) {
            ContextCompat.startForegroundService(context, serviceIntent)
        } else {
            context.stopService(serviceIntent)
        }
    }

    LaunchedEffect(Unit) {
        val (_, savedStatus) = BackendApi().fetchStatus()
        if (savedStatus != null) {
            growwConfigured = savedStatus.growwConfigured
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
                    onLiveEnabledChange = { requested ->
                        liveEnabled = requested && (lastValidation?.liveExecutionReady == true)
                    },
                    budget = budget,
                    onBudgetChange = { budget = it },
                    growwConfigured = growwConfigured,
                    validation = lastValidation
                )

                AppScreen.STRATEGIES -> StrategiesScreen(
                    modifier = Modifier.padding(padding)
                )

                AppScreen.SETTINGS -> GrowwSettingsScreen(
                    modifier = Modifier.padding(padding),
                    onConfigurationSaved = { growwConfigured = true },
                    onValidated = {
                        lastValidation = it
                        if (!it.liveExecutionReady) liveEnabled = false
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
    onLiveEnabledChange: (Boolean) -> Unit,
    budget: Float,
    onBudgetChange: (Float) -> Unit,
    growwConfigured: Boolean,
    validation: ValidationStatus?
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

        StatusCard(
            title = "Next trading day",
            primary = "Research queue not synced",
            secondary = "Syncs official exchange calendar + next listings"
        )

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
                                liveEnabled -> "ARMED — Groww and static IP checks passed"
                                validation?.liveExecutionReady == true -> "READY — switch on when you want live execution"
                                else -> "LOCKED — Groww + static IP validation required"
                            },
                            color = if (liveEnabled) Danger else Muted,
                            fontSize = 13.sp
                        )
                    }
                    Switch(
                        checked = liveEnabled,
                        enabled = validation?.liveExecutionReady == true,
                        onCheckedChange = onLiveEnabledChange
                    )
                }

                HorizontalDivider(color = Color(0xFF27313A))

                Text(
                    "Live budget  ₹" + NumberFormat.getNumberInstance(Locale("en", "IN"))
                        .format(budget.toInt()),
                    fontWeight = FontWeight.SemiBold
                )
                Slider(
                    value = budget,
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
            MetricCard("Shadow capital", "₹1,00,000", Modifier.weight(1f))
            MetricCard("Today P&L", "₹0", Modifier.weight(1f))
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
            onClick = { onLiveEnabledChange(false) }
        ) {
            Text("Emergency Disable", fontWeight = FontWeight.Bold)
        }
    }
}

@Composable
private fun StrategiesScreen(modifier: Modifier) {
    var summary by remember { mutableStateOf<StrategySummary?>(null) }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()
    val client = remember { BackendApi() }

    fun refresh() {
        if (busy) return
        busy = true
        error = null
        scope.launch {
            val (result, value) = client.fetchStrategySummary()
            busy = false
            if (result.ok && value != null) {
                summary = value
            } else {
                error = result.error ?: "Unable to load strategy statistics"
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

        error?.let {
            StatusCard(
                title = "Strategy service",
                primary = "UNAVAILABLE",
                secondary = it,
                primaryColor = Danger
            )
            OutlinedButton(onClick = { refresh() }, modifier = Modifier.fillMaxWidth()) {
                Text("Retry")
            }
        }

        summary?.let { data ->
            StatusCard(
                title = "Evidence source",
                primary = if (data.evidenceSource == "REMOTE") "REPLAY SYNCED" else "LOCAL CATALOG",
                secondary = if (data.evidenceSource == "REMOTE")
                    "Rankings use recorded replay evidence after trading costs."
                else
                    "All registered strategy families are visible now. Tested/champion metrics populate after replay evidence sync.",
                primaryColor = if (data.evidenceSource == "REMOTE") Teal else Amber
            )

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
                        "No strategy family has enough recorded replay evidence yet. IPO Sentinel will not label an untested family as working.",
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
                    "CHAMPION requires mature positive evidence after costs. CHALLENGER has sufficient testing but has not passed all promotion gates. RESEARCH is untested or has a small sample.",
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

            Text(
                data.rankingNote,
                color = Muted,
                fontSize = 11.sp,
                lineHeight = 16.sp
            )

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
private fun GrowwSettingsScreen(
    modifier: Modifier,
    onConfigurationSaved: () -> Unit,
    onValidated: (ValidationStatus) -> Unit
) {
    var totpToken by remember { mutableStateOf("") }
    var totpSecret by remember { mutableStateOf("") }
    var staticIp by rememberSaveable { mutableStateOf("") }
    var whitelistConfirmed by rememberSaveable { mutableStateOf(false) }

    var busy by remember { mutableStateOf(false) }
    var message by remember { mutableStateOf<String?>(null) }
    var messageColor by remember { mutableStateOf(Muted) }
    var status by remember { mutableStateOf<ConnectionStatus?>(null) }
    var validation by remember { mutableStateOf<ValidationStatus?>(null) }
    val scope = rememberCoroutineScope()
    val client = remember { BackendApi() }
    val context = LocalContext.current
    var notificationsAllowed by remember { mutableStateOf(NotificationHelper.notificationsAllowed(context)) }

    fun refreshStatus(showMessage: Boolean) {
        if (busy) return
        busy = true
        scope.launch {
            val (result, value) = client.fetchStatus()
            busy = false
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
            "Groww credentials, trade notifications and the whitelisted static public IP are managed here.",
            color = Muted,
            fontSize = 13.sp
        )

        SettingsSection("Notifications") {
            CheckRow("Order and execution notifications", notificationsAllowed)
            Text(
                "IPO Sentinel asks for Android notification permission on first launch. It does not need permission to read notifications from Groww or any other app; Groww API order status is the source of truth.",
                color = Muted,
                fontSize = 12.sp,
                lineHeight = 18.sp
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(
                    onClick = {
                        val intent = Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).apply {
                            putExtra(Settings.EXTRA_APP_PACKAGE, context.packageName)
                        }
                        context.startActivity(intent)
                    },
                    modifier = Modifier.weight(1f)
                ) {
                    Text("Notification Settings")
                }
                OutlinedButton(
                    onClick = {
                        notificationsAllowed = NotificationHelper.notificationsAllowed(context)
                        if (notificationsAllowed) NotificationHelper.showTest(context)
                    },
                    modifier = Modifier.weight(1f)
                ) {
                    Text("Test")
                }
            }
            TextButton(
                onClick = {
                    notificationsAllowed = NotificationHelper.notificationsAllowed(context)
                },
                modifier = Modifier.fillMaxWidth()
            ) {
                Text("Refresh notification status")
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
                        refreshStatus(showMessage = false)
                    } else {
                        message = result.error ?: "Save failed"
                        messageColor = Danger
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
                it.growwError?.let { error ->
                    Text("Groww: $error", color = Danger, fontSize = 12.sp)
                }
                it.egressError?.let { error ->
                    Text("Static IP: $error", color = Danger, fontSize = 12.sp)
                }
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
