package com.dhruva.multyfibridge;

import android.content.Context;
import android.content.SharedPreferences;
import org.json.JSONArray;
import org.json.JSONObject;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.HashSet;
import java.util.Locale;
import java.util.Set;
import java.util.TimeZone;

final class BridgeStore {
    private static final String PREFS = "dhruva_multyfi_bridge";
    private static final String KEY_LOGS = "logs";
    private static final String KEY_PROCESSED = "processed";

    static SharedPreferences prefs(Context context) {
        return context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }
    static boolean isArmed(Context context) { return prefs(context).getBoolean("armed", false); }
    static void setArmed(Context context, boolean armed) { prefs(context).edit().putBoolean("armed", armed).apply(); }
    static String gatewayUrl(Context context) { return prefs(context).getString("gateway_url", "").trim(); }
    static String apiToken(Context context) { return prefs(context).getString("api_token", "").trim(); }
    static String sourcePackage(Context context) { return prefs(context).getString("source_package", "").trim(); }

    static void saveConfig(Context context, String gateway, String token, String sourcePackage) {
        prefs(context).edit()
                .putString("gateway_url", gateway == null ? "" : gateway.trim())
                .putString("api_token", token == null ? "" : token.trim())
                .putString("source_package", sourcePackage == null ? "" : sourcePackage.trim())
                .apply();
    }

    static synchronized boolean isProcessed(Context context, String eventId) {
        return prefs(context).getStringSet(KEY_PROCESSED, new HashSet<String>()).contains(eventId);
    }

    static synchronized void markProcessed(Context context, String eventId) {
        Set<String> existing = new HashSet<>(prefs(context).getStringSet(KEY_PROCESSED, new HashSet<String>()));
        existing.add(eventId);
        prefs(context).edit().putStringSet(KEY_PROCESSED, existing).apply();
    }

    static synchronized void addLog(Context context, String status, String message) {
        try {
            JSONArray oldArray = new JSONArray(prefs(context).getString(KEY_LOGS, "[]"));
            JSONArray newArray = new JSONArray();
            JSONObject row = new JSONObject();
            row.put("time", nowIst());
            row.put("status", status);
            row.put("message", message);
            newArray.put(row);
            for (int i = 0; i < oldArray.length() && i < 79; i++) newArray.put(oldArray.get(i));
            prefs(context).edit().putString(KEY_LOGS, newArray.toString()).apply();
        } catch (Exception ignored) { }
    }

    static String formattedLogs(Context context) {
        try {
            JSONArray array = new JSONArray(prefs(context).getString(KEY_LOGS, "[]"));
            if (array.length() == 0) return "No notifications processed yet.";
            StringBuilder out = new StringBuilder();
            for (int i = 0; i < array.length(); i++) {
                JSONObject row = array.getJSONObject(i);
                out.append(row.optString("time")).append("  •  ").append(row.optString("status"))
                        .append("\n").append(row.optString("message")).append("\n\n");
            }
            return out.toString().trim();
        } catch (Exception ignored) { return "Unable to read local event log."; }
    }

    static void clearLogs(Context context) { prefs(context).edit().putString(KEY_LOGS, "[]").apply(); }

    private static String nowIst() {
        SimpleDateFormat format = new SimpleDateFormat("dd MMM, HH:mm:ss", Locale.US);
        format.setTimeZone(TimeZone.getTimeZone("Asia/Kolkata"));
        return format.format(new Date()) + " IST";
    }
}
