package com.suhas.iposentinel

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.launch

private val Ink = Color(0xFF0F1318)
private val Card = Color(0xFF171D23)
private val Teal = Color(0xFF21D4B4)
private val Danger = Color(0xFFFF6B6B)
private val Muted = Color(0xFF9AA7B3)
private val Amber = Color(0xFFFFC857)

private enum class AppScreen { DASHBOARD, SETTINGS }

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { IpoSentinelApp() }
    }
}

@Composable
private fun IpoSentinelApp() {
    var screen by rememberSaveable { mutableStateOf(AppScreen.DASHBOARD) }
    var liveEnabled by rememberSaveable { mutableStateOf(false) }
    var budget by rememberSaveable { mutableFloatStateOf(100_000f) }
    var lastValidation by remember { mutableStateOf<ValidationStatus?>(null) }
    var growwConfigured by remember { mutableStateOf(false) }

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
                        selected = screen == AppScreen.SETTINGS,
                        onClick = { screen = AppScreen.SETTINGS },
                        icon = { Text("⚙") },
                        label = { Text("Groww Setup") }
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
                    validation = lastValidation,
                    openSettings = { screen = AppScreen.SETTINGS }
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
    validation: ValidationStatus?,
    openSettings: () -> Unit
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
            title = "Groww + Static IP",
            primary = readiness,
            secondary = when {
                validation?.liveExecutionReady == true ->
                    "Groww authentication and backend egress IP validation passed"
                growwConfigured ->
                    "Credentials saved. Open Groww Setup and validate connection."
                else ->
                    "Add backend URL, Groww TOTP token, secret and whitelisted static IP"
            },
            primaryColor = if (validation?.liveExecutionReady == true) Teal else Amber
        )

        if (!growwConfigured) {
            Button(
                onClick = openSettings,
                modifier = Modifier.fillMaxWidth()
            ) {
                Text("Configure Groww Connection")
            }
        }

        StatusCard(
            title = "Next trading day",
            primary = "Research queue not synced",
            secondary = "Backend resolves official exchange calendar + next listings"
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
                                liveEnabled -> "ARMED — backend validation passed"
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

                Text("Live budget  ₹" + budget.toInt(), fontWeight = FontWeight.SemiBold)
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
private fun GrowwSettingsScreen(
    modifier: Modifier,
    onConfigurationSaved: () -> Unit,
    onValidated: (ValidationStatus) -> Unit
) {
    var backendUrl by rememberSaveable { mutableStateOf("") }
    var adminKey by rememberSaveable { mutableStateOf("") }
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

    fun api(): BackendApi? {
        if (!backendUrl.trim().startsWith("https://")) {
            message = "Backend URL must start with https://"
            messageColor = Danger
            return null
        }
        if (adminKey.isBlank()) {
            message = "Enter the backend admin key"
            messageColor = Danger
            return null
        }
        return BackendApi(backendUrl.trim(), adminKey)
    }

    Column(
        modifier = modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(18.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp)
    ) {
        Text("Groww & Backend Setup", fontSize = 28.sp, fontWeight = FontWeight.Bold)
        Text(
            "Credentials are sent to your backend over HTTPS and encrypted there. The APK does not persist the Groww TOTP token or secret.",
            color = Muted,
            fontSize = 13.sp
        )

        SettingsSection("1. Backend") {
            OutlinedTextField(
                value = backendUrl,
                onValueChange = { backendUrl = it },
                label = { Text("Backend HTTPS URL") },
                placeholder = { Text("https://ipo-sentinel.example.com") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri)
            )
            OutlinedTextField(
                value = adminKey,
                onValueChange = { adminKey = it },
                label = { Text("Backend admin key") },
                visualTransformation = PasswordVisualTransformation(),
                singleLine = true,
                modifier = Modifier.fillMaxWidth()
            )
            Text(
                "The admin key protects the credential-management endpoints. It is not your Groww token.",
                color = Muted,
                fontSize = 12.sp
            )
        }

        SettingsSection("2. Groww TOTP") {
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
                "The secret is used server-side to generate the current one-time password. It is never returned by the backend.",
                color = Muted,
                fontSize = 12.sp
            )
        }

        SettingsSection("3. Static IP") {
            OutlinedTextField(
                value = staticIp,
                onValueChange = { staticIp = it.trim() },
                label = { Text("Whitelisted backend static public IP") },
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
                    "I have whitelisted this public IP in Groww",
                    modifier = Modifier.weight(1f)
                )
            }
            Text(
                "Use the backend server's public egress IP — not your phone IP or home Wi-Fi IP. Validation compares the real backend egress IP with this value.",
                color = Muted,
                fontSize = 12.sp
            )
        }

        Button(
            onClick = {
                val client = api() ?: return@Button
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
                        // Deliberately remove broker secrets from UI memory immediately after save.
                        totpToken = ""
                        totpSecret = ""
                        onConfigurationSaved()
                        message = "Encrypted Groww configuration saved on backend"
                        messageColor = Teal
                    } else {
                        message = result.error ?: "Save failed"
                        messageColor = Danger
                    }
                }
            },
            enabled = !busy,
            modifier = Modifier.fillMaxWidth().height(50.dp)
        ) {
            Text("Save encrypted configuration")
        }

        OutlinedButton(
            onClick = {
                val client = api() ?: return@OutlinedButton
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
                            "Validation completed — one or more readiness checks failed"
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
            onClick = {
                val client = api() ?: return@TextButton
                busy = true
                scope.launch {
                    val (result, value) = client.fetchStatus()
                    busy = false
                    if (result.ok && value != null) {
                        status = value
                        if (!value.expectedStaticIp.isNullOrBlank()) staticIp = value.expectedStaticIp
                        whitelistConfirmed = value.staticIpConfirmed
                        message = "Backend status refreshed"
                        messageColor = Teal
                    } else {
                        message = result.error ?: "Status check failed"
                        messageColor = Danger
                    }
                }
            },
            enabled = !busy,
            modifier = Modifier.fillMaxWidth()
        ) {
            Text("Refresh backend status")
        }

        if (busy) {
            LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
        }

        message?.let {
            Text(it, color = messageColor, fontWeight = FontWeight.SemiBold)
        }

        status?.let {
            SettingsSection("Backend status") {
                CheckRow("Encrypted secret store", it.secretStoreReady)
                CheckRow("Groww credentials configured", it.growwConfigured)
                CheckRow("Static IP marked as whitelisted", it.staticIpConfirmed)
            }
        }

        validation?.let {
            SettingsSection("Validation result") {
                CheckRow("Groww TOTP authentication", it.growwAuthOk)
                CheckRow("Backend egress IP matches", it.staticIpMatches)
                CheckRow("Static IP whitelist confirmed", it.staticIpConfirmed)
                CheckRow("Encrypted secret store ready", it.secretStoreReady)
                HorizontalDivider(color = Color(0xFF27313A))
                Text(
                    "Detected egress IP: " + (it.detectedEgressIp ?: "Unavailable"),
                    color = Muted,
                    fontSize = 12.sp
                )
                Text(
                    "Expected static IP: " + (it.expectedStaticIp ?: "Not configured"),
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
                    Text("Network: $error", color = Danger, fontSize = 12.sp)
                }
            }
        }

        Text(
            "Security: Groww secrets are intentionally never displayed after saving. To change them, enter the new values and save again.",
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
