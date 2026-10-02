package com.suhas.iposentinel

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

private val Ink = Color(0xFF0F1318)
private val Card = Color(0xFF171D23)
private val Teal = Color(0xFF21D4B4)
private val Danger = Color(0xFFFF6B6B)
private val Muted = Color(0xFF9AA7B3)

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { IpoSentinelApp() }
    }
}

@Composable
private fun IpoSentinelApp() {
    var liveEnabled by remember { mutableStateOf(false) }
    var budget by remember { mutableFloatStateOf(100_000f) }

    MaterialTheme(
        colorScheme = darkColorScheme(
            primary = Teal,
            secondary = Teal,
            background = Ink,
            surface = Card,
            error = Danger
        )
    ) {
        Surface(modifier = Modifier.fillMaxSize(), color = Ink) {
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .verticalScroll(rememberScrollState())
                    .padding(18.dp),
                verticalArrangement = Arrangement.spacedBy(14.dp)
            ) {
                Text("IPO Sentinel", fontSize = 30.sp, fontWeight = FontWeight.Bold)
                Text("Listing-day intelligence • NSE", color = Muted)

                StatusCard(
                    title = "Next trading day",
                    primary = "Research queue not synced",
                    secondary = "Backend will resolve official NSE calendar + next listings"
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
                                    if (liveEnabled) "ARMED — backend must still be execution-ready" else "OFF — shadow mode only",
                                    color = if (liveEnabled) Danger else Muted,
                                    fontSize = 13.sp
                                )
                            }
                            Switch(checked = liveEnabled, onCheckedChange = { liveEnabled = it })
                        }

                        Divider(color = Color(0xFF27313A))

                        Text("Live budget  ₹" + budget.toInt(), fontWeight = FontWeight.SemiBold)
                        Slider(
                            value = budget,
                            onValueChange = { budget = (it / 5_000f).toInt() * 5_000f },
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
                    onClick = { liveEnabled = false }
                ) {
                    Text("Emergency Disable", fontWeight = FontWeight.Bold)
                }
            }
        }
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
private fun StatusCard(title: String, primary: String, secondary: String) {
    ElevatedCard(colors = CardDefaults.elevatedCardColors(containerColor = Card)) {
        Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(title, color = Muted, fontSize = 12.sp)
            Text(primary, fontSize = 20.sp, fontWeight = FontWeight.Bold)
            Text(secondary, color = Muted, fontSize = 13.sp)
        }
    }
}
