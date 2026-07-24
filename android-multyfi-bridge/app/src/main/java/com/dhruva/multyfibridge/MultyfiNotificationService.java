package com.dhruva.multyfibridge;

import android.app.Notification;
import android.content.pm.ApplicationInfo;
import android.os.Bundle;
import android.service.notification.NotificationListenerService;
import android.service.notification.StatusBarNotification;
import android.text.TextUtils;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

public class MultyfiNotificationService extends NotificationListenerService {
    @Override
    public void onNotificationPosted(StatusBarNotification sbn) {
        if (sbn == null || sbn.getNotification() == null) return;
        String packageName = sbn.getPackageName();
        if (!isAllowedSource(packageName)) return;

        String rawText = extractText(sbn.getNotification());
        SignalParser.ParsedSignal signal = SignalParser.parse(rawText, sbn.getPostTime());
        if (signal == null) {
            BridgeStore.addLog(this, "IGNORED", "Multyfi notification lacked Stock Name or Entry Range. Package: " + packageName);
            return;
        }

        String summary = signal.symbol + " | Entry ₹" + money(signal.entryLow) + "–₹" + money(signal.entryHigh)
                + " | GTT BUY 100 | cap ₹" + money(signal.maxBuyPrice);
        if (BridgeStore.isProcessed(this, signal.eventId)) {
            BridgeStore.addLog(this, "DUPLICATE", summary + " — already processed today.");
            return;
        }
        if (!BridgeStore.isArmed(this)) {
            BridgeStore.addLog(this, "CAPTURED", summary + " — auto-buy is OFF.");
            return;
        }
        if (BridgeStore.gatewayUrl(this).isEmpty()) {
            BridgeStore.addLog(this, "BLOCKED", summary + " — gateway URL is missing.");
            return;
        }

        BridgeStore.addLog(this, "SENDING", summary);
        BridgeClient.submit(getApplicationContext(), signal, packageName, (success, message) -> {
            if (success) {
                BridgeStore.markProcessed(getApplicationContext(), signal.eventId);
                BridgeStore.addLog(getApplicationContext(), "ORDER ACCEPTED", summary + "\n" + message);
            } else {
                BridgeStore.addLog(getApplicationContext(), "FAILED", summary + "\n" + message);
            }
        });
    }

    private boolean isAllowedSource(String packageName) {
        String configured = BridgeStore.sourcePackage(this);
        if (!configured.isEmpty()) return configured.equals(packageName);
        try {
            ApplicationInfo info = getPackageManager().getApplicationInfo(packageName, 0);
            String label = String.valueOf(getPackageManager().getApplicationLabel(info)).toLowerCase(Locale.US);
            return label.contains("multyfi") || label.contains("multify");
        } catch (Exception ignored) { return false; }
    }

    private static String extractText(Notification notification) {
        Bundle extras = notification.extras;
        if (extras == null) return "";
        List<String> parts = new ArrayList<>();
        add(parts, extras.getCharSequence(Notification.EXTRA_TITLE));
        add(parts, extras.getCharSequence(Notification.EXTRA_TEXT));
        add(parts, extras.getCharSequence(Notification.EXTRA_BIG_TEXT));
        add(parts, extras.getCharSequence(Notification.EXTRA_SUB_TEXT));
        CharSequence[] lines = extras.getCharSequenceArray(Notification.EXTRA_TEXT_LINES);
        if (lines != null) for (CharSequence line : lines) add(parts, line);
        return TextUtils.join("\n", parts);
    }

    private static void add(List<String> parts, CharSequence value) {
        if (value == null) return;
        String text = value.toString().trim();
        if (!text.isEmpty() && !parts.contains(text)) parts.add(text);
    }

    private static String money(double value) {
        if (Math.rint(value) == value) return String.format(Locale.US, "%.0f", value);
        return String.format(Locale.US, "%.2f", value);
    }
}
