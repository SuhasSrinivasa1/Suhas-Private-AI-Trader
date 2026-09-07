package com.intradayone.mobile

import android.app.Application
import android.content.Intent
import androidx.core.content.ContextCompat
import com.intradayone.mobile.service.MarketSessionService
import java.time.DayOfWeek
import java.time.LocalTime
import java.time.ZoneId
import java.time.ZonedDateTime

/**
 * V2.3 bootstrap: if Android creates the app process during the NSE session,
 * make sure the foreground market scanner is alive. Candidate ingestion also
 * starts the service from SessionRepository, so Multyfi notifications remain
 * the primary trigger even when the UI is closed.
 */
class MultyfiApplication : Application() {
    override fun onCreate() {
        super.onCreate()
        val now = ZonedDateTime.now(ZoneId.of("Asia/Kolkata"))
        val tradingDay = now.dayOfWeek !in setOf(DayOfWeek.SATURDAY, DayOfWeek.SUNDAY)
        val time = now.toLocalTime()
        val scannerWindow = !time.isBefore(LocalTime.of(8, 50)) && time.isBefore(LocalTime.of(15, 31))
        if (tradingDay && scannerWindow) {
            try {
                ContextCompat.startForegroundService(
                    this,
                    Intent(this, MarketSessionService::class.java)
                )
            } catch (_: Throwable) {
                // SessionRepository will retry as soon as a Multyfi candidate is ingested.
            }
        }
    }
}
