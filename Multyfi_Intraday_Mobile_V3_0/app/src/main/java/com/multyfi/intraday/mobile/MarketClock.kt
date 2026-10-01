package com.multyfi.intraday.mobile

import java.time.DayOfWeek
import java.time.Instant
import java.time.LocalTime
import java.time.ZoneId
import java.time.ZonedDateTime

object MarketClock {
    val IST: ZoneId = ZoneId.of("Asia/Kolkata")
    private val open = LocalTime.of(9, 15)
    private val entryLock = LocalTime.of(14, 55)
    private val forceFlat = LocalTime.of(15, 15)
    private val exchangeClose = LocalTime.of(15, 30)

    fun now(): ZonedDateTime = ZonedDateTime.now(IST)
    fun now(ts: Long): ZonedDateTime = Instant.ofEpochMilli(ts).atZone(IST)

    fun isWeekday(z: ZonedDateTime = now()): Boolean =
        z.dayOfWeek != DayOfWeek.SATURDAY && z.dayOfWeek != DayOfWeek.SUNDAY

    fun exchangeState(z: ZonedDateTime = now()): String {
        if (!isWeekday(z)) return "CLOSED"
        val t = z.toLocalTime()
        return if (!t.isBefore(open) && t.isBefore(exchangeClose)) "OPEN" else "CLOSED"
    }

    fun canOpenNewPaperRisk(z: ZonedDateTime = now()): Boolean =
        isWeekday(z) && !z.toLocalTime().isBefore(open) && z.toLocalTime().isBefore(entryLock)

    fun shouldForceFlat(z: ZonedDateTime = now()): Boolean =
        !isWeekday(z) || !z.toLocalTime().isBefore(forceFlat)

    fun isTrackingWindow(z: ZonedDateTime = now()): Boolean =
        isWeekday(z) && !z.toLocalTime().isBefore(open) && z.toLocalTime().isBefore(exchangeClose)

    fun dayKey(ts: Long = System.currentTimeMillis()): String = now(ts).toLocalDate().toString()

    fun nextLearningTriggerMillis(): Long {
        var z = now().withHour(15).withMinute(22).withSecond(0).withNano(0)
        if (!z.isAfter(now())) z = z.plusDays(1)
        while (!isWeekday(z)) z = z.plusDays(1)
        return z.toInstant().toEpochMilli()
    }

    fun tokenDay(ts: Long = System.currentTimeMillis()): String {
        var z = now(ts)
        if (z.toLocalTime().isBefore(LocalTime.of(6, 0))) z = z.minusDays(1)
        return z.toLocalDate().toString()
    }
}
