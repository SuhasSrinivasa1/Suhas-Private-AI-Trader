package com.dhruva.multyfibridge;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;
import java.util.TimeZone;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

final class SignalParser {
    static final int QUANTITY = 100;
    static final double BUFFER_PERCENT = 1.0d;

    private static final Pattern STOCK_PATTERN = Pattern.compile(
            "(?i)stock\\s*name\\s*[:\\-]\\s*([A-Z][A-Z0-9&._\\-]{0,24})");
    private static final Pattern ENTRY_PATTERN = Pattern.compile(
            "(?i)entry\\s*range\\s*[:\\-]\\s*(?:₹|rs\\.?|inr)?\\s*([0-9,]+(?:\\.[0-9]+)?)\\s*(?:-|–|—|to)\\s*(?:₹|rs\\.?|inr)?\\s*([0-9,]+(?:\\.[0-9]+)?)");

    static ParsedSignal parse(String rawText, long notificationTimeMillis) {
        if (rawText == null) return null;
        Matcher stockMatcher = STOCK_PATTERN.matcher(rawText);
        Matcher entryMatcher = ENTRY_PATTERN.matcher(rawText);
        if (!stockMatcher.find() || !entryMatcher.find()) return null;

        String symbol = stockMatcher.group(1).toUpperCase(Locale.US).trim();
        double first = parsePrice(entryMatcher.group(1));
        double second = parsePrice(entryMatcher.group(2));
        if (symbol.isEmpty() || first <= 0 || second <= 0) return null;

        double low = Math.min(first, second);
        double high = Math.max(first, second);
        double maxBuy = BigDecimal.valueOf(high * 1.01d).setScale(2, RoundingMode.HALF_UP).doubleValue();
        String eventId = sha256(istDay(notificationTimeMillis) + "|" + symbol + "|" + low + "|" + high);
        return new ParsedSignal(eventId, symbol, low, high, maxBuy, notificationTimeMillis, rawText);
    }

    private static double parsePrice(String value) {
        try { return Double.parseDouble(value.replace(",", "")); }
        catch (Exception ignored) { return -1d; }
    }

    private static String istDay(long millis) {
        SimpleDateFormat format = new SimpleDateFormat("yyyy-MM-dd", Locale.US);
        format.setTimeZone(TimeZone.getTimeZone("Asia/Kolkata"));
        return format.format(new Date(millis));
    }

    private static String sha256(String text) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] bytes = digest.digest(text.getBytes(StandardCharsets.UTF_8));
            StringBuilder builder = new StringBuilder();
            for (byte b : bytes) builder.append(String.format(Locale.US, "%02x", b));
            return builder.toString();
        } catch (Exception ignored) {
            return Integer.toHexString(text.hashCode());
        }
    }

    static final class ParsedSignal {
        final String eventId;
        final String symbol;
        final double entryLow;
        final double entryHigh;
        final double maxBuyPrice;
        final long notificationTimeMillis;
        final String rawText;

        ParsedSignal(String eventId, String symbol, double entryLow, double entryHigh,
                     double maxBuyPrice, long notificationTimeMillis, String rawText) {
            this.eventId = eventId;
            this.symbol = symbol;
            this.entryLow = entryLow;
            this.entryHigh = entryHigh;
            this.maxBuyPrice = maxBuyPrice;
            this.notificationTimeMillis = notificationTimeMillis;
            this.rawText = rawText;
        }
    }
}
