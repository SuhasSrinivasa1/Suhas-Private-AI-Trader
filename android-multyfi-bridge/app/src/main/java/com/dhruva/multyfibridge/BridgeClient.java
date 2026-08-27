package com.dhruva.multyfibridge;

import android.content.Context;
import org.json.JSONObject;
import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

final class BridgeClient {
    interface Callback { void onResult(boolean success, String message); }

    static void submit(Context context, SignalParser.ParsedSignal signal, String sourcePackage, Callback callback) {
        String gateway = BridgeStore.gatewayUrl(context);
        if (gateway.isEmpty()) {
            callback.onResult(false, "Gateway URL is not configured.");
            return;
        }
        new Thread(() -> {
            HttpURLConnection connection = null;
            try {
                JSONObject payload = new JSONObject();
                payload.put("event_id", signal.eventId);
                payload.put("source", "multyfi_android_notification");
                payload.put("source_package", sourcePackage);
                payload.put("symbol", signal.symbol);
                payload.put("exchange", "NSE");
                payload.put("segment", "CASH");
                payload.put("product", "CNC");
                payload.put("order_type", "GTT_BUY");
                payload.put("quantity", SignalParser.QUANTITY);
                payload.put("entry_low", signal.entryLow);
                payload.put("entry_high", signal.entryHigh);
                payload.put("trigger_price", signal.entryHigh);
                payload.put("price_buffer_percent", SignalParser.BUFFER_PERCENT);
                payload.put("max_buy_price", signal.maxBuyPrice);
                payload.put("execution_policy", "CATCH_WITHIN_1_PERCENT");
                payload.put("target", JSONObject.NULL);
                payload.put("stop_loss", JSONObject.NULL);
                payload.put("auto_sell", false);
                payload.put("notification_time_epoch_ms", signal.notificationTimeMillis);
                payload.put("raw_notification", signal.rawText);

                connection = open(gateway, "POST");
                String token = BridgeStore.apiToken(context);
                if (!token.isEmpty()) connection.setRequestProperty("Authorization", "Bearer " + token);
                byte[] body = payload.toString().getBytes(StandardCharsets.UTF_8);
                connection.setFixedLengthStreamingMode(body.length);
                try (OutputStream output = connection.getOutputStream()) { output.write(body); }
                int code = connection.getResponseCode();
                String response = readBody(code >= 200 && code < 400 ? connection.getInputStream() : connection.getErrorStream());
                if (code >= 200 && code < 300) {
                    callback.onResult(true, "Gateway accepted GTT BUY for " + signal.symbol + " (HTTP " + code + ").");
                } else {
                    callback.onResult(false, "Gateway rejected order (HTTP " + code + "): " + trim(response));
                }
            } catch (Exception e) {
                callback.onResult(false, "Gateway error: " + e.getClass().getSimpleName() + " — " + e.getMessage());
            } finally {
                if (connection != null) connection.disconnect();
            }
        }, "dhruva-order-submit").start();
    }

    static void test(String gateway, String token, Callback callback) {
        if (gateway == null || gateway.trim().isEmpty()) {
            callback.onResult(false, "Enter the Dhruva gateway URL first.");
            return;
        }
        new Thread(() -> {
            HttpURLConnection connection = null;
            try {
                connection = open(gateway.trim(), "GET");
                connection.setRequestProperty("X-Dhruva-Bridge-Test", "true");
                if (token != null && !token.trim().isEmpty()) connection.setRequestProperty("Authorization", "Bearer " + token.trim());
                int code = connection.getResponseCode();
                callback.onResult(code >= 200 && code < 500, "Gateway response: HTTP " + code + ".");
            } catch (Exception e) {
                callback.onResult(false, "Connection failed: " + e.getMessage());
            } finally {
                if (connection != null) connection.disconnect();
            }
        }, "dhruva-gateway-test").start();
    }

    private static HttpURLConnection open(String url, String method) throws Exception {
        HttpURLConnection connection = (HttpURLConnection) new URL(url).openConnection();
        connection.setRequestMethod(method);
        connection.setConnectTimeout(8000);
        connection.setReadTimeout(12000);
        connection.setUseCaches(false);
        connection.setRequestProperty("Accept", "application/json");
        connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
        if ("POST".equals(method)) connection.setDoOutput(true);
        return connection;
    }

    private static String readBody(InputStream input) {
        if (input == null) return "";
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(input, StandardCharsets.UTF_8))) {
            StringBuilder out = new StringBuilder();
            String line;
            while ((line = reader.readLine()) != null && out.length() < 1000) out.append(line);
            return out.toString();
        } catch (Exception ignored) { return ""; }
    }

    private static String trim(String text) {
        if (text == null || text.trim().isEmpty()) return "no response body";
        String clean = text.replace('\n', ' ').trim();
        return clean.length() <= 240 ? clean : clean.substring(0, 240) + "…";
    }
}
