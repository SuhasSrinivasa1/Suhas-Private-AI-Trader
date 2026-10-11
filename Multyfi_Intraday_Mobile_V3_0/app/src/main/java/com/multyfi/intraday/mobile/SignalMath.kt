package com.multyfi.intraday.mobile

import kotlin.math.max
import kotlin.math.sign
import kotlin.math.sqrt
import kotlin.math.tanh

object SignalMath {
    fun latest(ticks: List<MarketTick>): SignalFeature {
        if (ticks.isEmpty()) return SignalFeature(0L, 0.0, 0.0, 1.0, 0.0, "WAITING")
        return series(ticks).last()
    }

    fun series(ticks: List<MarketTick>): List<SignalFeature> {
        if (ticks.isEmpty()) return emptyList()
        val n = ticks.size
        val deltaVol = LongArray(n)
        val cumulativePv = DoubleArray(n)
        val cumulativeVol = LongArray(n)
        for (i in 0 until n) {
            val dv = if (i == 0) 0L else max(0L, ticks[i].volume - ticks[i - 1].volume)
            deltaVol[i] = dv
            cumulativeVol[i] = (if (i == 0) 0L else cumulativeVol[i - 1]) + dv
            cumulativePv[i] = (if (i == 0) 0.0 else cumulativePv[i - 1]) + ticks[i].price * dv.toDouble()
        }

        fun pct(i: Int, back: Int): Double {
            val j = max(0, i - back)
            val base = ticks[j].price
            return if (base > 0.0) (ticks[i].price / base - 1.0) * 100.0 else 0.0
        }

        fun volPct(i: Int): Double {
            val start = max(1, i - 12)
            if (i - start + 1 < 3) return 0.08
            val rs = ArrayList<Double>()
            for (k in start..i) {
                val p0 = ticks[k - 1].price
                val p1 = ticks[k].price
                if (p0 > 0.0) rs += (p1 / p0 - 1.0) * 100.0
            }
            if (rs.size < 2) return 0.08
            val m = rs.average()
            val v = rs.sumOf { (it - m) * (it - m) } / rs.size.toDouble()
            return max(0.03, sqrt(v))
        }

        fun rvol(i: Int): Double {
            if (i < 8) return 1.0
            val rStart = max(1, i - 2)
            val recent = (rStart..i).map { deltaVol[it].toDouble() }.average()
            val pEnd = rStart - 1
            val pStart = max(1, pEnd - 11)
            if (pEnd < pStart) return 1.0
            val prior = (pStart..pEnd).map { deltaVol[it].toDouble() }.average()
            return if (prior <= 0.0) 1.0 else (recent / prior).coerceIn(0.20, 3.00)
        }

        return ticks.indices.map { i ->
            val t = ticks[i]
            val m1 = pct(i, 12)
            val m3 = pct(i, 36)
            val m5 = pct(i, 60)
            val vol = volPct(i)
            val vwap = when {
                cumulativeVol[i] > 0L -> cumulativePv[i] / cumulativeVol[i].toDouble()
                t.averagePrice > 0.0 -> t.averagePrice
                else -> ticks.subList(max(0, i - 24), i + 1).map { it.price }.average()
            }
            val vwapPct = if (vwap > 0.0) (t.price / vwap - 1.0) * 100.0 else 0.0
            val rv = rvol(i)
            val denom = max(0.08, vol * 3.5)
            val directionalRvol = sign(m1) * (rv - 1.0).coerceIn(-1.5, 1.5)
            val raw = 0.42 * (m1 / denom) +
                0.24 * (m3 / (denom * 1.5)) +
                0.14 * (m5 / (denom * 2.0)) +
                0.16 * (vwapPct / 0.30) +
                0.04 * directionalRvol
            val score = tanh(raw).coerceIn(-1.0, 1.0)
            val trend = when {
                score >= 0.72 -> "STRONG_RISING"
                score >= 0.35 -> "RISING"
                score <= -0.72 -> "STRONG_FALLING"
                score <= -0.35 -> "FALLING"
                else -> "MIXED"
            }
            SignalFeature(t.ts, t.price, score, rv, vwapPct, trend)
        }
    }
}
