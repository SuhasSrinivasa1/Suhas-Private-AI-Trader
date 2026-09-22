package com.suhas.multyfideliverybuy;

import android.content.Context;
import android.content.SharedPreferences;

import java.util.Calendar;
import java.util.TimeZone;

final class AppPrefs {
    private static final String FILE = "fresh_delivery_buy_prefs";

    private AppPrefs() {}

    private static SharedPreferences p(Context c) {
        return c.getSharedPreferences(FILE, Context.MODE_PRIVATE);
    }

    static boolean isArmed(Context c) { return p(c).getBoolean("armed", false); }
    static void setArmed(Context c, boolean v) { p(c).edit().putBoolean("armed", v).apply(); }

    static boolean isSwingEnabled(Context c) { return p(c).getBoolean("swing", false); }
    static void setSwingEnabled(Context c, boolean v) { p(c).edit().putBoolean("swing", v).apply(); }

    static boolean isMultibaggerEnabled(Context c) { return p(c).getBoolean("multibagger", false); }
    static void setMultibaggerEnabled(Context c, boolean v) { p(c).edit().putBoolean("multibagger", v).apply(); }

    static String getApiKey(Context c) { return p(c).getString("api_key", ""); }
    static void setApiKey(Context c, String v) { p(c).edit().putString("api_key", clean(v)).apply(); }

    static String getTotpSecret(Context c) { return p(c).getString("totp_secret", ""); }
    static void setTotpSecret(Context c, String v) { p(c).edit().putString("totp_secret", clean(v)).apply(); }

    static String getExpectedStaticIp(Context c) { return p(c).getString("expected_static_ip", ""); }
    static void setExpectedStaticIp(Context c, String v) { p(c).edit().putString("expected_static_ip", clean(v)).apply(); }

    static String getAccessToken(Context c) { return p(c).getString("access_token", ""); }
    static void setAccessToken(Context c, String v) { p(c).edit().putString("access_token", clean(v)).apply(); }
    static void clearAccessToken(Context c) { p(c).edit().remove("access_token").apply(); }

    static String getLastDetectedIp(Context c) { return p(c).getString("last_detected_ip", ""); }
    static boolean isStaticIpMatch(Context c) { return p(c).getBoolean("static_ip_match", false); }
    static long getStaticIpCheckTime(Context c) { return p(c).getLong("static_ip_check_time", 0L); }
    static void setStaticIpCheck(Context c, String detectedIp, boolean match) {
        p(c).edit()
                .putString("last_detected_ip", clean(detectedIp))
                .putBoolean("static_ip_match", match)
                .putLong("static_ip_check_time", System.currentTimeMillis())
                .apply();
    }

    static boolean wasAuthTestSuccessful(Context c) { return p(c).getBoolean("auth_test_ok", false); }
    static long getAuthTestTime(Context c) { return p(c).getLong("auth_test_time", 0L); }
    static String getAuthTestMessage(Context c) { return p(c).getString("auth_test_message", "Not tested yet."); }
    static void setAuthTest(Context c, boolean ok, String message) {
        p(c).edit()
                .putBoolean("auth_test_ok", ok)
                .putLong("auth_test_time", System.currentTimeMillis())
                .putString("auth_test_message", message == null ? "" : message)
                .apply();
    }

    static void invalidateConnectionReadiness(Context c) {
        p(c).edit()
                .remove("access_token")
                .putBoolean("auth_test_ok", false)
                .putBoolean("static_ip_match", false)
                .putBoolean("armed", false)
                .apply();
    }

    static boolean isAuthTestFresh(Context c) {
        if (!wasAuthTestSuccessful(c) || getAccessToken(c).isEmpty()) return false;
        long testedAt = getAuthTestTime(c);
        if (testedAt <= 0L) return false;
        return testedAt >= currentGrowwTokenWindowStart(System.currentTimeMillis());
    }

    static boolean isReadyForBuy(Context c) {
        return isAuthTestFresh(c) && isStaticIpMatch(c) && !getExpectedStaticIp(c).isEmpty();
    }

    private static long currentGrowwTokenWindowStart(long now) {
        Calendar cal = Calendar.getInstance(TimeZone.getTimeZone("Asia/Kolkata"));
        cal.setTimeInMillis(now);
        cal.set(Calendar.HOUR_OF_DAY, 6);
        cal.set(Calendar.MINUTE, 0);
        cal.set(Calendar.SECOND, 0);
        cal.set(Calendar.MILLISECOND, 0);
        if (now < cal.getTimeInMillis()) cal.add(Calendar.DAY_OF_MONTH, -1);
        return cal.getTimeInMillis();
    }


    static int getManualBudget(Context c) { return p(c).getInt("manual_budget", 50000); }
    static void setManualBudget(Context c, int v) {
        int clamped = Math.max(0, Math.min(100000, (v / 10000) * 10000));
        p(c).edit().putInt("manual_budget", clamped).apply();
    }

    static String getManualStatus(Context c) { return p(c).getString("manual_status", "No manual LONG/SHORT order submitted yet."); }
    static long getManualStatusTime(Context c) { return p(c).getLong("manual_status_time", 0L); }
    static void setManualStatus(Context c, String v) {
        p(c).edit().putString("manual_status", v == null ? "" : v)
                .putLong("manual_status_time", System.currentTimeMillis()).apply();
    }

    static String getLastStatus(Context c) { return p(c).getString("last_status", "No order submitted yet."); }
    static void setLastStatus(Context c, String v) {
        p(c).edit().putString("last_status", v == null ? "" : v).putLong("last_status_time", System.currentTimeMillis()).apply();
    }
    static long getLastStatusTime(Context c) { return p(c).getLong("last_status_time", 0L); }

    static synchronized boolean claimFingerprint(Context c, String fingerprint) {
        SharedPreferences prefs = p(c);
        long now = System.currentTimeMillis();
        long prior = prefs.getLong("fp_" + fingerprint, 0L);
        if (prior > 0L && now - prior < 24L * 60L * 60L * 1000L) return false;
        prefs.edit().putLong("fp_" + fingerprint, now).apply();
        return true;
    }

    private static String clean(String v) { return v == null ? "" : v.trim(); }
}
