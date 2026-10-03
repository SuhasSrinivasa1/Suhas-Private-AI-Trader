package com.suhas.iposentinel

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat

object NotificationHelper {
    const val LIVE_CHANNEL = "ipo_sentinel_live"
    const val ORDER_CHANNEL = "ipo_sentinel_orders"
    const val LIVE_SERVICE_NOTIFICATION_ID = 1001

    fun createChannels(context: Context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val manager = context.getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(
            NotificationChannel(
                LIVE_CHANNEL,
                "Live trading status",
                NotificationManager.IMPORTANCE_LOW
            ).apply {
                description = "Persistent status while IPO Sentinel live monitoring is enabled."
            }
        )
        manager.createNotificationChannel(
            NotificationChannel(
                ORDER_CHANNEL,
                "Order activity",
                NotificationManager.IMPORTANCE_HIGH
            ).apply {
                description = "Order placement, fills, exits, rejections and risk alerts."
            }
        )
    }

    fun notificationsAllowed(context: Context): Boolean {
        if (!NotificationManagerCompat.from(context).areNotificationsEnabled()) {
            return false
        }
        return Build.VERSION.SDK_INT < 33 ||
            ContextCompat.checkSelfPermission(
                context,
                Manifest.permission.POST_NOTIFICATIONS
            ) == PackageManager.PERMISSION_GRANTED
    }

    fun liveServiceNotification(context: Context): android.app.Notification {
        return NotificationCompat.Builder(context, LIVE_CHANNEL)
            .setSmallIcon(android.R.drawable.stat_notify_sync)
            .setContentTitle("IPO Sentinel Live")
            .setContentText("Monitoring live order lifecycle events")
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .build()
    }

    fun showOrderEvent(context: Context, event: OrderLifecycleEvent) {
        if (!notificationsAllowed(context)) return

        val title = when (event.eventType) {
            "LIVE_ENABLED" -> "Live trading enabled"
            "LIVE_DISABLED" -> "Live trading disabled"
            "ORDER_PLACING" -> "Order being placed"
            "ORDER_ACCEPTED" -> "Order accepted"
            "ORDER_PARTIAL" -> "Order partially filled"
            "ORDER_FILLED" -> "Order executed"
            "EXIT_PLACING" -> "Exit order being placed"
            "POSITION_CLOSED" -> "Position closed"
            "ORDER_REJECTED" -> "Order rejected"
            "ORDER_CANCELLED" -> "Order cancelled"
            "RISK_HALT" -> "Risk halt"
            "FORCE_FLAT_STARTED" -> "Intraday force-exit started"
            else -> "IPO Sentinel activity"
        }

        val parts = mutableListOf<String>()
        event.symbol?.let { parts += it }
        event.side?.let { parts += it }
        event.quantity?.let { qty -> parts += "Qty " + qty }
        event.price?.let { px -> parts += "₹" + String.format("%.2f", px) }
        if (!event.message.isNullOrBlank()) parts += event.message

        val body = parts.joinToString(" • ").ifBlank { "Order lifecycle update" }
        val notification = NotificationCompat.Builder(context, ORDER_CHANNEL)
            .setSmallIcon(
                if (event.eventType in setOf("ORDER_REJECTED", "RISK_HALT"))
                    android.R.drawable.stat_notify_error
                else
                    android.R.drawable.stat_sys_download_done
            )
            .setContentTitle(title)
            .setContentText(body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setAutoCancel(true)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .build()

        try {
            NotificationManagerCompat.from(context).notify(
                2000 + (event.id % 100000).toInt(),
                notification
            )
        } catch (_: SecurityException) {
            // Permission can be revoked while the live monitor is running.
        }
    }
}
