package com.suhas.iposentinel

import android.app.Service
import android.content.Intent
import android.os.IBinder
import kotlinx.coroutines.*

class LiveNotificationService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var pollJob: Job? = null

    override fun onCreate() {
        super.onCreate()
        NotificationHelper.createChannels(this)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            stopMonitoring()
            return START_NOT_STICKY
        }

        startForeground(
            NotificationHelper.LIVE_SERVICE_NOTIFICATION_ID,
            NotificationHelper.liveServiceNotification(this)
        )
        startPolling()
        return START_NOT_STICKY
    }

    private fun startPolling() {
        if (pollJob?.isActive == true) return
        pollJob = scope.launch {
            val prefs = getSharedPreferences("ipo_sentinel_live_events", MODE_PRIVATE)
            var lastId = prefs.getLong("last_order_event_id", 0L)
            var delayMs = 3_000L

            while (isActive) {
                val (result, batch) = BackendApi().fetchOrderEvents(lastId)
                if (result.ok && batch != null) {
                    for (event in batch.events) {
                        NotificationHelper.showOrderEvent(this@LiveNotificationService, event)
                        lastId = maxOf(lastId, event.id)
                    }
                    prefs.edit().putLong("last_order_event_id", lastId).apply()
                    delayMs = 3_000L
                } else {
                    delayMs = (delayMs * 2).coerceAtMost(30_000L)
                }
                delay(delayMs)
            }
        }
    }

    private fun stopMonitoring() {
        pollJob?.cancel()
        pollJob = null
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    companion object {
        const val ACTION_STOP = "com.suhas.iposentinel.STOP_LIVE_NOTIFICATION_SERVICE"
    }
}
