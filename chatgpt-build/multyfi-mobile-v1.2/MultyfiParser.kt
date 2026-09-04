package com.intradayone.mobile.notification

enum class RecommendationType { FREE_EQUITY, PAID_EQUITY_INTRADAY, UPDATE, EXIT, UNKNOWN }

data class MultyfiEvent(
    val title: String,
    val text: String,
    val symbol: String?,
    val kind: String,
    val receivedAtMs: Long,
    val recommendationType: RecommendationType = RecommendationType.UNKNOWN,
    val target: Double? = null,
    val entryLow: Double? = null,
    val entryHigh: Double? = null,
    val stopLoss: Double? = null
)

object MultyfiParser {
    const val MULTYFI_PACKAGE = "com.multyfi.invest"

    private val reject = listOf(
        "multibagger", "swing", "positional", "btst", "stbt", "option", "future",
        "commodity", "gold", "silver", "crude", "nifty", "banknifty", "long term"
    )
    private val paidIntraday = listOf(
        "released: equity intraday trade", "equity intraday trade", "equity intraday",
        "intraday equity", "intraday trade", "intraday call"
    )
    private val freeEquity = listOf(
        "today's free equity recommendation", "todays free equity recommendation",
        "free equity recommendation"
    )
    private val exits = listOf(
        "book profit", "book profits", "trade closed", "close trade", "closed below target",
        "target achieved", "exit price", "exit"
    )
    private val updates = listOf(" update", "update:", "update ·", "update |")

    fun parse(packageName: String, title: String, text: String, whenMs: Long): MultyfiEvent? {
        if (packageName != MULTYFI_PACKAGE) return null
        val raw = "$title\n$text"
        val combined = raw.lowercase()
        if (reject.any(combined::contains)) return null

        val type = when {
            exits.any(combined::contains) -> RecommendationType.EXIT
            freeEquity.any(combined::contains) -> RecommendationType.FREE_EQUITY
            paidIntraday.any(combined::contains) -> RecommendationType.PAID_EQUITY_INTRADAY
            updates.any(combined::contains) || title.trim().endsWith("Update", ignoreCase = true) -> RecommendationType.UPDATE
            else -> RecommendationType.UNKNOWN
        }

        // Accept only the two requested recommendation families plus updates/exits for already-known symbols.
        if (type == RecommendationType.UNKNOWN) return null

        val symbol = extractSymbol(raw)
        val kind = when (type) {
            RecommendationType.FREE_EQUITY, RecommendationType.PAID_EQUITY_INTRADAY -> "CALL"
            RecommendationType.EXIT -> "EXIT"
            RecommendationType.UPDATE -> "UPDATE"
            else -> "UNKNOWN"
        }

        val target = extractNumberAfterLabel(raw, listOf("Target"))
        val stop = extractNumberAfterLabel(raw, listOf("Stop Loss", "Stoploss", "SL"))
        val range = extractEntryRange(raw)

        return MultyfiEvent(
            title = title,
            text = text,
            symbol = symbol,
            kind = kind,
            receivedAtMs = whenMs,
            recommendationType = type,
            target = target,
            entryLow = range?.first,
            entryHigh = range?.second,
            stopLoss = stop
        )
    }

    private fun extractSymbol(raw: String): String? {
        // Most reliable form from Multyfi recommendation notifications.
        Regex("(?i)stock\\s*name\\s*[:：]\\s*([A-Z][A-Z0-9&.-]{1,14})")
            .find(raw)?.groupValues?.getOrNull(1)?.uppercase()?.let { return it }

        // Book Profit : UNIPARTS / Trade Closed Below Target – SRF / UNIPARTS Update
        Regex("(?i)book\\s*profit\\s*[:：-]\\s*([A-Z][A-Z0-9&.-]{1,14})")
            .find(raw)?.groupValues?.getOrNull(1)?.uppercase()?.let { return it }
        Regex("(?i)trade\\s*closed[^A-Z0-9&.-]+([A-Z][A-Z0-9&.-]{1,14})")
            .find(raw)?.groupValues?.getOrNull(1)?.uppercase()?.let { return it }
        Regex("(?i)^\\s*([A-Z][A-Z0-9&.-]{1,14})\\s+update\\b")
            .find(raw)?.groupValues?.getOrNull(1)?.uppercase()?.let { return it }

        val stopWords = setOf(
            "BUY", "SELL", "INTRADAY", "EQUITY", "TRADE", "CALL", "EXIT", "TARGET", "STOPLOSS",
            "SL", "NSE", "BSE", "TODAY", "FREE", "RECOMMENDATION", "RELEASED", "UPDATE", "BOOK",
            "PROFIT", "PRICE", "RETURN", "RETURNS", "DURATION", "NEW", "TRADES", "SOON", "FOCUS"
        )
        return Regex("\\b[A-Z][A-Z0-9&.-]{2,14}\\b")
            .findAll(raw)
            .map { it.value.uppercase() }
            .firstOrNull { it !in stopWords && it.length <= 12 }
    }

    private fun extractEntryRange(raw: String): Pair<Double, Double>? {
        val m = Regex("(?i)entry\\s*range\\s*[:：]\\s*₹?\\s*([0-9]+(?:\\.[0-9]+)?)\\s*[-–—to]+\\s*₹?\\s*([0-9]+(?:\\.[0-9]+)?)")
            .find(raw) ?: return null
        val a = m.groupValues[1].toDoubleOrNull() ?: return null
        val b = m.groupValues[2].toDoubleOrNull() ?: return null
        return if (a <= b) a to b else b to a
    }

    private fun extractNumberAfterLabel(raw: String, labels: List<String>): Double? {
        for (label in labels) {
            val m = Regex("(?i)${Regex.escape(label)}\\s*[:：]\\s*₹?\\s*([0-9]+(?:\\.[0-9]+)?)").find(raw)
            val v = m?.groupValues?.getOrNull(1)?.toDoubleOrNull()
            if (v != null) return v
        }
        return null
    }
}
