package com.intradayone.mobile.notification

data class MultyfiEvent(
    val title: String,
    val text: String,
    val symbol: String?,
    val kind: String,
    val receivedAtMs: Long,
    val source: String = "UNKNOWN"
)

object MultyfiParser {
    const val MULTYFI_PACKAGE = "com.multyfi.invest"

    private val reject = listOf(
        "multibagger", "swing", "positional", "btst", "stbt", "option", "future",
        "commodity", "gold", "silver", "crude", "nifty", "banknifty", "long term"
    )
    private val paidIntraday = listOf(
        "equity intraday", "intraday equity", "equity intraday trade", "intraday trade", "intraday call"
    )
    private val freeEquity = listOf(
        "today's free equity recommendation", "todays free equity recommendation", "free equity recommendation"
    )
    private val exits = listOf(
        "book profit", "book profits", "trade closed", "closed below target", "close trade", "exit price", "target achieved"
    )
    private val updates = listOf(" update", "update:", "intraday update")

    fun parse(packageName: String, title: String, text: String, whenMs: Long): MultyfiEvent? {
        if (packageName != MULTYFI_PACKAGE) return null
        val raw = "$title $text"
        val combined = raw.lowercase()
        if (reject.any(combined::contains)) return null

        val symbol = probableSymbol(raw)
        val isFree = freeEquity.any(combined::contains)
        val isPaid = paidIntraday.any(combined::contains) && combined.contains("equity")
        val isExit = exits.any(combined::contains)
        val isUpdate = updates.any(combined::contains)

        return when {
            isExit && !symbol.isNullOrBlank() -> MultyfiEvent(title, text, symbol, "EXIT", whenMs, "UPDATE")
            isFree && !symbol.isNullOrBlank() -> MultyfiEvent(title, text, symbol, "CALL", whenMs, "FREE_EQUITY")
            isPaid && !symbol.isNullOrBlank() -> MultyfiEvent(title, text, symbol, "CALL", whenMs, "PAID_INTRADAY")
            isUpdate && !symbol.isNullOrBlank() -> MultyfiEvent(title, text, symbol, "UPDATE", whenMs, "UPDATE")
            else -> null
        }
    }

    private fun probableSymbol(raw: String): String? {
        val stockName = Regex("(?i)stock\\s*name\\s*[:\\-]\\s*([A-Z][A-Z0-9&.\\-]{1,14})")
            .find(raw)?.groupValues?.getOrNull(1)?.uppercase()
        if (!stockName.isNullOrBlank()) return stockName

        val stop = setOf(
            "BUY", "SELL", "INTRADAY", "EQUITY", "TRADE", "CALL", "EXIT", "TARGET",
            "STOPLOSS", "SL", "NSE", "BSE", "TODAY", "FREE", "RECOMMENDATION", "RELEASED",
            "UPDATE", "BOOK", "PROFIT", "RETURNS", "DURATION", "CAPITAL"
        )
        return Regex("\\b[A-Z][A-Z0-9&.-]{2,14}\\b").findAll(raw)
            .map { it.value.uppercase() }
            .firstOrNull { it !in stop && it.length <= 12 }
    }
}
