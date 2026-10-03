package com.suhas.iposentinel

import android.app.Service
import android.content.Intent
import android.os.IBinder
import kotlinx.coroutines.*

class TradeEventService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var pollingJob: Job? = null

    override fun onCreate() {
        super.onCreate()
        NotificationHelper.createChannels(this)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        startForeground(
            NotificationHelper.FOREGROUND_NOTIFICATION_ID,
            NotificationHelper.foregroundNotification(this)
        )

        if (pollingJob?.isActive != true) {
            pollingJob = scope.launch { pollEvents() }
        }
        return START_STICKY
    }

    private suspend fun pollEvents() {
        val prefs = getSharedPreferences("ipo_sentinel_events", MODE_PRIVATE)
        var lastId = prefs.getLong("last_event_id", 0L)
        val api = BackendApi()

        while (currentCoroutineContext().isActive) {
            val (result, events) = api.fetchTradeEvents(lastId, timeoutSeconds = 2)
            if (result.ok) {
                for (event in events.sortedBy { it.id }) {
                    if (event.id <= lastId) continue
                    NotificationHelper.showTradeEvent(this, event)
                    lastId = event.id
                    prefs.edit().putLong("last_event_id", lastId).apply()
                }
                delay(2_000)
            } else {
                delay(5_000)
            }
        }
    }

    override fun onDestroy() {
        pollingJob?.cancel()
        scope.cancel()
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null
}
