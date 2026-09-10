package com.multyfi.intraday.mobile

import android.content.Context
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.util.Locale

class GrowwInstrumentCatalog(private val context: Context) {
    companion object {
        private const val INSTRUMENT_URL = "https://growwapi-assets.groww.in/instruments/instrument.csv"
        private const val CACHE_MAX_AGE_MS = 12L * 60L * 60L * 1000L
        private val symbolPattern = Regex("[A-Z][A-Z0-9&.\\-]{1,24}")
    }

    private val cacheFile = File(context.filesDir, "groww_nse_cash_symbols.txt")

    @Volatile
    private var memory: Set<String>? = null

    fun cachedSymbols(): Set<String> {
        memory?.let { if (it.isNotEmpty()) return it }
        val loaded = readCache()
        if (loaded.isNotEmpty()) memory = loaded
        return loaded
    }

    fun loadOrRefresh(force: Boolean = false): Set<String> {
        val cached = cachedSymbols()
        val fresh = cacheFile.exists() && System.currentTimeMillis() - cacheFile.lastModified() < CACHE_MAX_AGE_MS
        if (!force && fresh && cached.size >= 500) return cached

        return runCatching { downloadOfficialCatalog() }
            .onSuccess { memory = it }
            .getOrElse { error ->
                if (cached.size >= 500) cached else throw error
            }
    }

    fun matchNotification(text: String, symbols: Set<String>): String? {
        if (symbols.isEmpty()) return null
        val upper = text.uppercase(Locale.US)

        val explicit = Regex("(?:NSE\\s*[:/_\\-]\\s*)([A-Z][A-Z0-9&.\\-]{1,24})")
            .findAll(upper)
            .map { it.groupValues[1] }
            .firstOrNull { it in symbols }
        if (explicit != null) return explicit

        return Regex("[A-Z][A-Z0-9&.\\-]{1,24}")
            .findAll(upper)
            .map { it.value.trim('.', '-') }
            .filter { it.length >= 2 && symbolPattern.matches(it) }
            .firstOrNull { it in symbols }
    }

    private fun readCache(): Set<String> {
        if (!cacheFile.exists()) return emptySet()
        return runCatching {
            cacheFile.readLines()
                .asSequence()
                .map { it.trim().uppercase(Locale.US) }
                .filter { symbolPattern.matches(it) }
                .toSet()
        }.getOrDefault(emptySet())
    }

    private fun downloadOfficialCatalog(): Set<String> {
        val conn = (URL(INSTRUMENT_URL).openConnection() as HttpURLConnection).apply {
            requestMethod = "GET"
            connectTimeout = 10_000
            readTimeout = 15_000
            setRequestProperty("Accept", "text/csv,*/*")
            useCaches = false
        }
        try {
            if (conn.responseCode !in 200..299) error("Groww instrument catalog HTTP ${conn.responseCode}")
            val reader = conn.inputStream.bufferedReader()
            val headerLine = reader.readLine() ?: error("Groww instrument catalog is empty")
            val header = parseCsvLine(headerLine).map { it.trim().lowercase(Locale.US) }
            val exchangeIdx = header.indexOf("exchange")
            val symbolIdx = header.indexOf("trading_symbol")
            val segmentIdx = header.indexOf("segment")
            val typeIdx = header.indexOf("instrument_type")
            require(exchangeIdx >= 0 && symbolIdx >= 0 && segmentIdx >= 0) {
                "Groww instrument catalog columns are incomplete"
            }

            val out = LinkedHashSet<String>()
            reader.useLines { lines ->
                lines.forEach { line ->
                    if (line.isBlank()) return@forEach
                    val cols = parseCsvLine(line)
                    val needed = maxOf(exchangeIdx, symbolIdx, segmentIdx, typeIdx)
                    if (cols.size <= needed) return@forEach
                    val exchange = cols[exchangeIdx].trim().uppercase(Locale.US)
                    val segment = cols[segmentIdx].trim().uppercase(Locale.US)
                    if (exchange != "NSE" || segment != "CASH") return@forEach
                    val instrumentType = if (typeIdx >= 0) cols[typeIdx].trim().uppercase(Locale.US) else ""
                    if (instrumentType == "INDEX") return@forEach
                    val symbol = cols[symbolIdx].trim().uppercase(Locale.US)
                    if (symbolPattern.matches(symbol)) out += symbol
                }
            }
            require(out.size >= 500) { "Groww instrument catalog returned only ${out.size} NSE CASH symbols" }

            val tmp = File(context.filesDir, "groww_nse_cash_symbols.tmp")
            tmp.writeText(out.sorted().joinToString("\n", postfix = "\n"))
            if (cacheFile.exists()) cacheFile.delete()
            if (!tmp.renameTo(cacheFile)) {
                cacheFile.writeText(tmp.readText())
                tmp.delete()
            }
            return out
        } finally {
            conn.disconnect()
        }
    }

    private fun parseCsvLine(line: String): List<String> {
        val out = ArrayList<String>()
        val cell = StringBuilder()
        var quoted = false
        var i = 0
        while (i < line.length) {
            val ch = line[i]
            when {
                ch == '"' && quoted && i + 1 < line.length && line[i + 1] == '"' -> {
                    cell.append('"')
                    i++
                }
                ch == '"' -> quoted = !quoted
                ch == ',' && !quoted -> {
                    out += cell.toString()
                    cell.setLength(0)
                }
                else -> cell.append(ch)
            }
            i++
        }
        out += cell.toString()
        return out
    }
}
