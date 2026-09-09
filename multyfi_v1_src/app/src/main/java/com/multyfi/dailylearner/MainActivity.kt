package com.multyfi.dailylearner

import android.app.Activity
import android.content.Intent
import android.graphics.Typeface
import android.os.Bundle
import android.view.Gravity
import android.widget.*
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Date
import java.util.Locale

class MainActivity : Activity() {
    private lateinit var repo: AppRepository
    private val engine = LearningEngine()
    private lateinit var content: LinearLayout
    private var pendingExport: String? = null
    private val dayFmt = SimpleDateFormat("yyyy-MM-dd", Locale.US)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        repo = AppRepository(this)
        maybeRunDailyLearning()
        buildShell()
        showLive()
    }

    private fun buildShell() {
        val root = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(24,24,24,12) }
        content = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        val sc = ScrollView(this).apply { addView(content); layoutParams = LinearLayout.LayoutParams(-1,0,1f) }
        val nav = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER }
        listOf("Live" to ::showLive, "Review" to ::showReview, "Activity" to ::showActivity, "Settings" to ::showSettings).forEach { (t, fn) ->
            nav.addView(Button(this).apply { text=t; setOnClickListener { fn() } }, LinearLayout.LayoutParams(0,-2,1f))
        }
        root.addView(sc); root.addView(nav)
        setContentView(root)
    }

    private fun title(t:String) = TextView(this).apply { text=t; textSize=30f; setTypeface(null, Typeface.BOLD); setPadding(0,12,0,20) }
    private fun line(t:String,bold:Boolean=false) = TextView(this).apply { text=t; textSize=18f; if (bold) setTypeface(null,Typeface.BOLD); setPadding(0,8,0,8) }
    private fun clear(t:String) { content.removeAllViews(); content.addView(title(t)) }

    private fun showLive() {
        clear("Live")
        val events=repo.todayEvents(); val closed=events.filter{it.action.equals("CLOSE",true)}
        val pnl=closed.sumOf{it.pnl}; val acc=if(closed.isEmpty())0.0 else closed.count{it.pnl>0}*100.0/closed.size
        content.addView(line("● SYSTEM READY",true))
        content.addView(line("Paper-learning engine active • local diagnostics enabled"))
        content.addView(line("Accuracy ${"%.1f".format(acc)}% • Paper P&L ${"%.2f".format(pnl)}",true))
        content.addView(line("Completed trades: ${closed.size}"))
        content.addView(line("This clean build does not place broker orders. Connect a real market/broker provider before live execution."))
        val add=Button(this).apply { text="Add sample completed paper trade"; setOnClickListener { addSampleTrade(); showLive() } }
        content.addView(add)
    }

    private fun addSampleTrade() {
        val n=repo.todayEvents().count{it.action=="CLOSE"}
        val pnl=if(n%3==0) 180.0 else -120.0
        repo.logEvent(TradeEvent(System.currentTimeMillis(), if(n%2==0)"DEMOA" else "DEMOB", if(n%2==0)"LONG" else "SHORT", "CLOSE", 100.0+n, pnl,
            if(pnl>0)"profit trail" else "protective stop", if(n%2==0)0.74 else -0.71, 1.2+n*0.1, if(n%2==0)0.3 else -0.2))
    }

    private fun showReview() {
        clear("Daily learning")
        val c=repo.currentConfig(); val today=repo.todayEvents().filter{it.action.equals("CLOSE",true)}
        content.addView(line("Every completed paper trade is stored locally and can contribute to the guarded daily learning pass."))
        content.addView(line("Champion enter=${c.enter} flip=${c.flip} exit=${c.exit}",true))
        content.addView(line(repo.lastLearningLine() ?: "No completed learning pass yet."))
        content.addView(Button(this).apply { text="Run Daily Learning Now"; setOnClickListener { runLearning(); showReview() } })
        content.addView(Button(this).apply { text="Download Daily Diagnostic (.txt)"; setOnClickListener { exportDiagnostic() } })
        content.addView(line("Completed paper trades today: ${today.size}"))
    }

    private fun showActivity() {
        clear("Activity")
        val sdf=SimpleDateFormat("yyyy-MM-dd HH:mm:ss",Locale.US)
        repo.todayEvents().sortedByDescending{it.ts}.take(100).forEach { e ->
            content.addView(line("• ${sdf.format(Date(e.ts))} ${e.symbol} ${e.side} ${e.action} P&L ${e.pnl} — ${e.reason}"))
        }
        if(repo.todayEvents().isEmpty()) content.addView(line("No events yet."))
    }

    private fun showSettings() {
        clear("Settings")
        content.addView(line("● READY",true))
        content.addView(line("Package: com.multyfi.dailylearner"))
        content.addView(line("Version: 1.0"))
        content.addView(line("Data: local app storage"))
        content.addView(line("Learning policy: evaluate daily; promote only when validation improves"))
    }

    private fun runLearning() {
        val before=repo.currentConfig()
        val result=engine.learn(repo.allEvents(), before)
        if(result.promoted) repo.saveConfig(result.championAfter)
        repo.recordLearning(result)
        Toast.makeText(this, if(result.promoted)"Challenger promoted" else "Champion kept", Toast.LENGTH_LONG).show()
    }

    private fun maybeRunDailyLearning() {
        val now=Calendar.getInstance()
        val afterCutoff= now.get(Calendar.HOUR_OF_DAY) > 15 || (now.get(Calendar.HOUR_OF_DAY)==15 && now.get(Calendar.MINUTE)>=15)
        val ranToday=repo.lastLearningTs()>0 && dayFmt.format(Date(repo.lastLearningTs()))==dayFmt.format(Date())
        if(afterCutoff && !ranToday) runLearning()
    }

    private fun exportDiagnostic() {
        pendingExport=DiagnosticExporter.build(this,repo)
        val name="Multyfi_Diagnostic_${dayFmt.format(Date())}.txt"
        val i=Intent(Intent.ACTION_CREATE_DOCUMENT).apply { addCategory(Intent.CATEGORY_OPENABLE); type="text/plain"; putExtra(Intent.EXTRA_TITLE,name) }
        startActivityForResult(i,7001)
    }

    @Deprecated("Deprecated in Java")
    override fun onActivityResult(requestCode:Int,resultCode:Int,data:Intent?) {
        super.onActivityResult(requestCode,resultCode,data)
        if(requestCode==7001 && resultCode==RESULT_OK && data?.data!=null) {
            contentResolver.openOutputStream(data.data!!)?.use { it.write((pendingExport?:"").toByteArray()) }
            Toast.makeText(this,"Diagnostic saved",Toast.LENGTH_LONG).show()
            pendingExport=null
        }
    }
}
