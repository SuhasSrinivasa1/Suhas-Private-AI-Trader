package com.multyfi.intraday.mobile

import android.app.AlarmManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import java.util.concurrent.Executors

class LearningAlarmReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent?) {
        val pending = goAsync()
        Executors.newSingleThreadExecutor().execute {
            try {
                val repo = AppRepository(context)
                repo.todayCandidates().forEach { c -> repo.saveCandidate(PaperEngine.forceFlat(repo, c)) }
                if (!repo.learningUpToDate()) {
                    val result = ReplayEngine().learn(repo)
                    if (result.promoted) repo.saveConfig(result.championAfter)
                    repo.recordLearning(result)
                }
                LearningScheduler.scheduleNext(context)
            } finally {
                pending.finish()
            }
        }
    }
}

object LearningScheduler {
    fun scheduleNext(context: Context) {
        val am = context.getSystemService(Context.ALARM_SERVICE) as AlarmManager
        val pi = PendingIntent.getBroadcast(
            context, 3022, Intent(context, LearningAlarmReceiver::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        am.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, MarketClock.nextLearningTriggerMillis(), pi)
    }
}

class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent?) {
        LearningScheduler.scheduleNext(context)
    }
}
