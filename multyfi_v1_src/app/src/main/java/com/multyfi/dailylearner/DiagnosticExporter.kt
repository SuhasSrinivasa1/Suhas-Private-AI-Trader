package com.multyfi.dailylearner

import android.content.Context
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlin.math.max

object DiagnosticExporter {
    private val sdf = SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.US)

    fun build(context: Context, repo: AppRepository): String {
        val events = repo.todayEvents()
        val closed = events.filter { it.action.equals("CLOSE", true) }
        val wins = closed.count { it.pnl > 0 }
        val pnl = closed.sumOf { it.pnl }
        val accuracy = if (closed.isEmpty()) 0.0 else wins * 100.0 / closed.size
        var running = 0.0
        var peak = 0.0
        var maxDd = 0.0
        var grossProfit = 0.0
        var grossLoss = 0.0
        closed.forEach {
            running += it.pnl
            peak = max(peak, running)
            maxDd = max(maxDd, peak - running)
            if (it.pnl > 0) grossProfit += it.pnl else grossLoss += -it.pnl
        }
        val pf = if (grossLoss == 0.0) 0.0 else grossProfit / grossLoss
        val c = repo.currentConfig()
        val last = repo.lastLearningLine() ?: "NONE"

        return buildString {
            appendLine("MULTYFI DAILY LEARNER DIAGNOSTIC")
            appendLine("App version: 1.0")
            appendLine("Generated: ${sdf.format(Date())}")
            appendLine()
            appendLine("TODAY")
            appendLine("Completed trades: ${closed.size}")
            appendLine("Wins: $wins")
            appendLine("Losses: ${closed.size - wins}")
            appendLine("Accuracy: ${"%.1f".format(accuracy)}%")
            appendLine("Paper P&L: ${"%.2f".format(pnl)}")
            appendLine("Profit factor: ${"%.2f".format(pf)}")
            appendLine("Max drawdown: ${"%.2f".format(maxDd)}")
            appendLine()
            appendLine("ACTIVE CHAMPION")
            appendLine("enter=${c.enter}")
            appendLine("flip=${c.flip}")
            appendLine("exit=${c.exit}")
            appendLine()
            appendLine("LAST LEARNING RESULT")
            appendLine(last)
            appendLine()
            appendLine("TRADE / ACTIVITY LOG")
            events.sortedBy { it.ts }.forEach { e ->
                appendLine("${sdf.format(Date(e.ts))} | ${e.symbol} | ${e.side} | ${e.action} | price=${e.price} | pnl=${e.pnl} | score=${e.score} | RVOL=${e.rvol} | VWAP%=${e.vwapPct} | ${e.reason}")
            }
            appendLine()
            appendLine("DAILY LEARNING STATUS: ${if (repo.lastLearningTs() > 0 && repo.dayString(repo.lastLearningTs()) == repo.dayString(System.currentTimeMillis())) "COMPLETED" else "NOT COMPLETED"}")
            appendLine("TODAY INCLUDED IN LEARNING: ${if (repo.lastLearningTs() > 0 && repo.dayString(repo.lastLearningTs()) == repo.dayString(System.currentTimeMillis())) "YES" else "NO"}")
            appendLine("NEXT SESSION CONFIG: enter=${c.enter} flip=${c.flip} exit=${c.exit}")
        }
    }
}
