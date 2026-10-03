package com.suhas.iposentinel

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat

object NotificationHelper {
    const val CHANNEL_ORDERS = "ipo_sentinel_orders"
    const val CHANNEL_SERVICE = "ipo_sentinel_live_monitor"
    const val FOREGROUND_NOTIFICATION_ID = 7001

    fun createChannels(context: Context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val manager = context.getSystemService(NotificationManager::class.java)

        val orders = NotificationChannel(
            CHANNEL_ORDERS,
            "Trade activity",
            NotificationManager.IMPORTANCE_HIGH
        ).apply {
            description = "IPO Sentinel order placement, fills, exits and failures"
            lockscreenVisibility = Notification.VISIBILITY_PRIVATE
            enableVibration(true)
        }

        val service = NotificationChannel(
            CHANNEL_SERVICE,
            "Live trading monitor",
            NotificationManager.IMPORTANCE_LOW
        ).apply {
            description = "Persistent status while live trading is armed"
            lockscreenVisibility = Notification.VISIBILITY_PRIVATE
        }

        manager.createNotificationChannel(orders)
        manager.createNotificationChannel(service)
    }

    fun notificationsAllowed(context: Context): Boolean {
        if (!NotificationManagerCompat.from(context).areNotificationsEnabled()) return false
        return Build.VERSION.SDK_INT < 33 ||
            ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) ==
            PackageManager.PERMISSION_GRANTED
    }

    fun foregroundNotification(context: Context): Notification =
        NotificationCompat.Builder(context, CHANNEL_SERVICE)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle("IPO Sentinel live monitor")
            .setContentText("Live trading is armed. Order events are being monitored.")
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setVisibility(NotificationCompat.VISIBILITY_PRIVATE)
            .setContentIntent(openAppIntent(context))
            .build()

    fun showTradeEvent(context: Context, event: TradeEvent) {
        if (!notificationsAllowed(context)) return

        val title = when (event.eventType.uppercase()) {
            "ORDER_PLACING" -> "Order being placed"
            "ORDER_SUBMITTED", "ORDER_ACCEPTED" -> "Order accepted"
            "ORDER_PARTIAL_FILL", "ORDER_PARTIAL" -> "Order partially filled"
            "ORDER_EXECUTED", "ORDER_FILLED" -> "Order executed"
            "EXIT_PLACING" -> "Closing order being placed"
            "EXIT_SUBMITTED" -> "Closing order submitted"
            "EXIT_PARTIAL_FILL" -> "Closing order partially filled"
            "EXIT_EXECUTED", "POSITION_CLOSED" -> "Position closed"
            "ORDER_REJECTED", "ORDER_FAILED", "EXIT_REJECTED", "EXIT_FAILED" -> "Order failed"
            "ORDER_CANCELLED", "EXIT_CANCELLED" -> "Order cancelled"
            "LIVE_ENABLED" -> "Live trading enabled"
            "LIVE_DISABLED" -> "Live trading disabled"
            "RISK_HALT" -> "Trading halted by risk controls"
            "FORCE_FLAT_STARTED" -> "Forced intraday exit started"
            else -> "IPO Sentinel trade update"
        }

        val pieces = mutableListOf<String>()
        event.symbol?.let { pieces += it }
        event.side?.let { pieces += it }
        event.quantity?.let { pieces += "Qty $it" }
        event.price?.let { pieces += "₹" + String.format(java.util.Locale.US, "%.2f", it) }
        if (event.message.isNotBlank()) pieces += event.message
        val body = pieces.joinToString(" • ").ifBlank { "Trade status updated" }

        val notification = NotificationCompat.Builder(context, CHANNEL_ORDERS)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle(title)
            .setContentText(body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setAutoCancel(true)
            .setVisibility(NotificationCompat.VISIBILITY_PRIVATE)
            .setContentIntent(openAppIntent(context))
            .build()

        try {
            NotificationManagerCompat.from(context).notify(
                (10_000 + (event.id % 1_000_000)).toInt(),
                notification
            )
        } catch (_: SecurityException) {
        }
    }

    fun showTest(context: Context) {
        showTradeEvent(
            context,
            TradeEvent(
                id = System.currentTimeMillis(),
                eventType = "ORDER_ACCEPTED",
                symbol = "TEST",
                side = "BUY",
                quantity = 1,
                price = 100.0,
                orderId = null,
                message = "Notifications are enabled",
                createdAt = ""
            )
        )
    }

    private fun openAppIntent(context: Context): PendingIntent {
        val intent = Intent(context, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP
        }
        return PendingIntent.getActivity(
            context,
            7002,
            intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
    }
}
