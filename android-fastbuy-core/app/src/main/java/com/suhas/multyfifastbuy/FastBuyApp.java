package com.suhas.multyfifastbuy;

import android.app.Application;
import android.content.Context;
import android.content.Intent;
import android.os.Process;
import android.os.SystemClock;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.time.LocalDate;
import java.time.LocalTime;
import java.time.ZoneId;
import java.util.Iterator;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;

public class FastBuyApp extends Application {
    private static FastBuyApp INSTANCE;
    private TradingEngine engine;

    @Override public void onCreate() {
        super.onCreate();
        INSTANCE = this;
        engine = new TradingEngine(this);
    }

    public static FastBuyApp get() { return INSTANCE; }
    public TradingEngine engine() { return engine; }
}

final class TradingEngine {
    enum State { WAITING, BUYING, HOLDING, SELLING, CLOSED }
    interface UiSink { void onStatus(String status); }

    private static final ZoneId IST = ZoneId.of("Asia/Kolkata");
    private final Context app;
    private final GrowwClient groww = new GrowwClient();
    private final ExecutorService fast = Executors.newSingleThreadExecutor(r -> {
        Thread t = new Thread(() -> { Process.setThreadPriority(Process.THREAD_PRIORITY_URGENT_DISPLAY); r.run(); }, "FastBuyOrder");
        t.setDaemon(true); return t;
    });
    private final ScheduledExecutorService bg = Executors.newScheduledThreadPool(2);
    private final AtomicBoolean marketPollBusy = new AtomicBoolean(false);

    private volatile UiSink ui;
    private volatile boolean armed;
    private volatile State state = State.WAITING;
    private volatile double cachedWallet;
    private volatile double dayCapitalSnapshot;
    private volatile double realizedGross;
    private volatile String dayKey = "";
    private volatile Call active;
    private volatile int quantity;
    private volatile double avgEntry;
    private volatile double lastLtp;
    private volatile double peakNetPct;
    private volatile double peakLtp;
    private volatile boolean adaptiveArmed;
    private volatile boolean adaptiveHasNextTick;
    private volatile boolean zeroBufferArmed;
    private volatile long monitorTicks;
    private volatile Telemetry telemetry = new Telemetry();

    TradingEngine(Context app) { this.app = app.getApplicationContext(); }

    void setUi(UiSink sink) { ui = sink; publish(); }
    void setToken(String token) { groww.setToken(token == null ? "" : token.trim()); publish("Token loaded in memory"); }
    boolean isArmed() { return armed; }
    State state() { return state; }
    String activeSymbol() { return active == null ? "" : active.symbol; }

    void routeTest() {
        bg.execute(() -> {
            try {
                double w = groww.getMisBalance();
                cachedWallet = w;
                publish(String.format(Locale.US, "Groww ready • MIS available ₹%,.2f", w));
            } catch (Exception e) { publish("Route test failed: " + shortErr(e)); }
        });
    }

    void arm() {
        if (!groww.hasToken()) { publish("Enter Groww access token first"); return; }
        bg.execute(() -> {
            try {
                double w = groww.getMisBalance();
                if (w <= 0) throw new IllegalStateException("MIS balance unavailable");
                cachedWallet = w;
                dayCapitalSnapshot = w;
                resetDayIfNeeded();
                armed = true;
                state = State.WAITING;
                Intent i = new Intent(app, TradingMonitorService.class);
                app.startService(i);
                publish(String.format(Locale.US, "ARMED • wallet snapshot ₹%,.2f • waiting for Multyfi Intraday", w));
                scheduleWalletRefresh();
            } catch (Exception e) { publish("ARM failed: " + shortErr(e)); }
        });
    }

    void disarm() {
        armed = false;
        app.stopService(new Intent(app, TradingMonitorService.class));
        publish("DISARMED");
    }

    void onNewCall(Call call, long notificationPostTimeMs) {
        if (!armed || call == null) return;
        long age = Math.max(0, System.currentTimeMillis() - notificationPostTimeMs);
        if (age > 20_000) { publish("Ignored stale Multyfi call • age " + age + " ms"); return; }
        resetDayIfNeeded();
        if (state != State.WAITING && state != State.CLOSED) { publish("Ignored new call • active trade " + activeSymbol()); return; }
        if (LocalTime.now(IST).isAfter(LocalTime.of(14,55))) { publish("New entries closed after 14:55 IST"); return; }

        telemetry = new Telemetry();
        telemetry.notificationPostWallMs = notificationPostTimeMs;
        telemetry.appReceiveElapsedNs = SystemClock.elapsedRealtimeNanos();
        active = call;
        state = State.BUYING;
        peakNetPct = 0; peakLtp = 0; adaptiveArmed = false; adaptiveHasNextTick = false; zeroBufferArmed = false; monitorTicks = 0;

        fast.execute(() -> {
            try {
                double wallet = cachedWallet > 0 ? cachedWallet : dayCapitalSnapshot;
                if (wallet <= 0) throw new IllegalStateException("No cached Groww wallet. Re-arm.");
                int q = (int)Math.floor((wallet * 0.99d) / call.entryHigh);
                if (q < 1) throw new IllegalStateException("Insufficient MIS wallet for " + call.symbol);
                quantity = q;
                telemetry.buyDispatchElapsedNs = SystemClock.elapsedRealtimeNanos();
                String orderId = groww.placeMarket(call.symbol, q, "BUY");
                telemetry.buyAckElapsedNs = SystemClock.elapsedRealtimeNanos();
                telemetry.buyOrderId = orderId;
                publish("BUY submitted • " + call.symbol + " • qty " + q + " • app dispatch " + telemetry.appDispatchMs() + " ms");
                reconcileBuy(0);
            } catch (Exception e) {
                state = State.WAITING; active = null; quantity = 0;
                publish("BUY failed: " + shortErr(e));
            }
        });
    }

    void onMultyfiEarlyExit(String symbol, String reason) {
        Call c = active;
        if (!armed || c == null || symbol == null || !c.symbol.equalsIgnoreCase(symbol)) return;
        if (state == State.BUYING || state == State.HOLDING) requestSell("MULTYFI EARLY EXIT • " + reason);
    }

    void monitorTick() {
        if (!armed) return;
        resetDayIfNeeded();
        if (state != State.HOLDING || active == null || quantity <= 0 || avgEntry <= 0) return;
        if (!marketPollBusy.compareAndSet(false, true)) return;
        bg.execute(() -> {
            try {
                double ltp = groww.getLtp(active.symbol);
                lastLtp = ltp;
                monitorTicks++;
                evaluateSell(ltp);
                if (monitorTicks % 8 == 0) reconcileManualExit();
            } catch (Exception ignored) {
            } finally { marketPollBusy.set(false); }
        });
    }

    private void evaluateSell(double ltp) {
        Call c = active; if (c == null || state != State.HOLDING) return;
        if (!LocalTime.now(IST).isBefore(LocalTime.of(14,58))) { requestSell("MANDATORY INTRADAY CLOSE"); return; }
        if (ltp >= c.target) { requestSell("MULTYFI TARGET REACHED"); return; }

        double entryNotional = avgEntry * quantity;
        double gross = (ltp - avgEntry) * quantity;
        double net = gross - ChargeEstimator.roundTrip(entryNotional, ltp * quantity);
        double netPct = entryNotional > 0 ? (net / entryNotional) * 100.0 : 0;

        // Day-level emergency only. There is deliberately NO per-stock downside stop.
        if (dayCapitalSnapshot > 0 && realizedGross + gross <= -(dayCapitalSnapshot * 0.02d)) {
            requestSell("DAILY GROSS LOSS −2.00%"); return;
        }

        if (netPct >= 1.0d) {
            if (!zeroBufferArmed) {
                zeroBufferArmed = true; peakLtp = ltp; peakNetPct = netPct;
                publish(String.format(Locale.US, "%s • +1%% NET zero-buffer armed • peak %.3f%%", c.symbol, netPct));
                return;
            }
            if (ltp > peakLtp) { peakLtp = ltp; peakNetPct = Math.max(peakNetPct, netPct); return; }
            if (ltp < peakLtp) { requestSell("+1% NET ZERO-BUFFER PEAK DECLINE"); }
            return;
        }

        if (netPct >= 0.50d) {
            if (!adaptiveArmed) {
                adaptiveArmed = true; adaptiveHasNextTick = false; peakNetPct = netPct;
                publish(String.format(Locale.US, "%s • adaptive protection armed at %.3f%% NET", c.symbol, netPct));
                return;
            }
            peakNetPct = Math.max(peakNetPct, netPct);
            if (!adaptiveHasNextTick) { adaptiveHasNextTick = true; return; }
            double floor = Math.max(0.25d, peakNetPct - 0.20d);
            if (netPct <= floor) requestSell(String.format(Locale.US, "ADAPTIVE NET FLOOR %.3f%%", floor));
        }
    }

    private void requestSell(String reason) {
        if (state == State.SELLING || active == null) return;
        state = State.SELLING;
        final Call c = active;
        fast.execute(() -> {
            try {
                Position p = quantity > 0 ? new Position(quantity, avgEntry) : groww.getPosition(c.symbol);
                int q = p.quantity > 0 ? p.quantity : quantity;
                if (q <= 0) { closeStrategy("Position already zero"); return; }
                telemetry.sellDispatchElapsedNs = SystemClock.elapsedRealtimeNanos();
                telemetry.sellOrderId = groww.placeMarket(c.symbol, q, "SELL");
                publish("SELL submitted • " + c.symbol + " • " + reason);
                reconcileSell(reason, 0);
            } catch (Exception e) {
                state = State.HOLDING;
                publish("SELL submission failed • still HOLDING • " + shortErr(e));
            }
        });
    }

    private void reconcileBuy(int attempt) {
        bg.schedule(() -> {
            try {
                Position p = groww.getPosition(active.symbol);
                if (p.quantity > 0 && p.avgPrice > 0) {
                    quantity = p.quantity; avgEntry = p.avgPrice; state = State.HOLDING;
                    telemetry.fillWallMs = System.currentTimeMillis();
                    publish(String.format(Locale.US, "HOLDING %s • qty %d • avg ₹%.2f • no downside auto-sell", active.symbol, quantity, avgEntry));
                    return;
                }
            } catch (Exception ignored) {}
            if (attempt < 50 && state == State.BUYING) reconcileBuy(attempt + 1);
            else if (state == State.BUYING) publish("BUY acknowledged; fill reconciliation still pending — position will NOT be auto-sold for missing protection");
        }, attempt < 20 ? 100 : 250, TimeUnit.MILLISECONDS);
    }

    private void reconcileSell(String reason, int attempt) {
        bg.schedule(() -> {
            try {
                Position p = groww.getPosition(active.symbol);
                if (p.quantity <= 0) {
                    double exit = lastLtp > 0 ? lastLtp : avgEntry;
                    realizedGross += (exit - avgEntry) * quantity;
                    closeStrategy(reason + " • position zero");
                    return;
                }
            } catch (Exception ignored) {}
            if (attempt < 50 && state == State.SELLING) reconcileSell(reason, attempt + 1);
            else if (state == State.SELLING) publish("SELL sent; waiting for Groww position zero");
        }, attempt < 20 ? 100 : 250, TimeUnit.MILLISECONDS);
    }

    private void reconcileManualExit() {
        if (active == null || state != State.HOLDING) return;
        try {
            Position p = groww.getPosition(active.symbol);
            if (p.quantity <= 0) closeStrategy("Manual/broker exit detected");
        } catch (Exception ignored) {}
    }

    private synchronized void closeStrategy(String reason) {
        String s = active == null ? "" : active.symbol;
        state = State.CLOSED; quantity = 0; avgEntry = 0; lastLtp = 0; active = null;
        publish("CLOSED " + s + " • " + reason + " • waiting for next fresh Multyfi call");
        state = State.WAITING;
    }

    private void scheduleWalletRefresh() {
        bg.schedule(() -> {
            if (!armed) return;
            if (state == State.WAITING) {
                try { cachedWallet = groww.getMisBalance(); } catch (Exception ignored) {}
            }
            scheduleWalletRefresh();
        }, 5, TimeUnit.SECONDS);
    }

    private void resetDayIfNeeded() {
        String now = LocalDate.now(IST).toString();
        if (!now.equals(dayKey)) { dayKey = now; realizedGross = 0; }
    }

    String statusText() {
        Call c = active;
        String trade = c == null ? "none" : c.symbol + " / " + state;
        return String.format(Locale.US, "%s • %s • wallet ₹%,.0f • trade %s", armed ? "ARMED" : "DISARMED", groww.hasToken() ? "Groww token ready" : "token missing", cachedWallet, trade);
    }

    private void publish() { publish(statusText()); }
    private void publish(String msg) {
        UiSink s = ui; if (s != null) s.onStatus(msg + "\n" + statusText());
    }
    private static String shortErr(Exception e) { String m = e.getMessage(); return m == null ? e.getClass().getSimpleName() : m; }
}

final class GrowwClient {
    private static final String BASE = "https://api.groww.in/v1";
    private volatile String token = "";
    void setToken(String t) { token = t == null ? "" : t.replaceFirst("(?i)^Bearer\\s+", "").trim(); }
    boolean hasToken() { return !token.isEmpty(); }

    double getMisBalance() throws Exception {
        JSONObject j = request("GET", BASE + "/margins/detail/user", null);
        Double d = findNumberByKey(j, "mis_balance_available");
        if (d == null) throw new IllegalStateException("mis_balance_available missing");
        return d;
    }

    String placeMarket(String symbol, int qty, String side) throws Exception {
        JSONObject b = new JSONObject();
        b.put("trading_symbol", symbol); b.put("quantity", qty); b.put("validity", "DAY");
        b.put("exchange", "NSE"); b.put("segment", "CASH"); b.put("product", "MIS");
        b.put("order_type", "MARKET"); b.put("transaction_type", side); b.put("price", 0);
        String ref = "FB" + Long.toString(System.currentTimeMillis()).substring(2);
        b.put("order_reference_id", ref.length() > 20 ? ref.substring(0,20) : ref);
        JSONObject j = request("POST", BASE + "/order/create", b);
        String id = findStringByKey(j, "groww_order_id");
        if (id == null) id = findStringByKey(j, "order_id");
        if (id == null) throw new IllegalStateException("Groww order id missing: " + j.toString());
        return id;
    }

    Position getPosition(String symbol) throws Exception {
        String u = BASE + "/positions/trading-symbol?trading_symbol=" + URLEncoder.encode(symbol, "UTF-8") + "&segment=CASH";
        JSONObject j = request("GET", u, null);
        JSONObject p = findObjectForSymbol(j, symbol);
        if (p == null) return new Position(0,0);
        int q = (int)Math.round(numberAny(p, "quantity", "net_quantity", "net_qty"));
        double a = numberAny(p, "average_price", "avg_price", "buy_average_price");
        return new Position(q, a);
    }

    double getLtp(String symbol) throws Exception {
        String key = "NSE_" + symbol;
        String u = BASE + "/live-data/ltp?segment=CASH&exchange_symbols=" + URLEncoder.encode(key, "UTF-8");
        JSONObject j = request("GET", u, null);
        Double direct = findNumberByKey(j, key);
        if (direct != null) return direct;
        Double ltp = findNumberByKey(j, "ltp");
        if (ltp == null) throw new IllegalStateException("LTP missing");
        return ltp;
    }

    private JSONObject request(String method, String url, JSONObject body) throws Exception {
        if (!hasToken()) throw new IllegalStateException("Groww token missing");
        HttpURLConnection c = (HttpURLConnection)new URL(url).openConnection();
        c.setConnectTimeout(2500); c.setReadTimeout(3500); c.setRequestMethod(method);
        c.setRequestProperty("Authorization", "Bearer " + token);
        c.setRequestProperty("Accept", "application/json"); c.setRequestProperty("Content-Type", "application/json");
        c.setRequestProperty("Connection", "keep-alive");
        if (body != null) {
            c.setDoOutput(true);
            byte[] bytes = body.toString().getBytes(StandardCharsets.UTF_8);
            c.setFixedLengthStreamingMode(bytes.length);
            try (OutputStream out = c.getOutputStream()) { out.write(bytes); }
        }
        int code = c.getResponseCode();
        InputStream in = code >= 200 && code < 300 ? c.getInputStream() : c.getErrorStream();
        StringBuilder sb = new StringBuilder();
        if (in != null) try (BufferedReader r = new BufferedReader(new InputStreamReader(in, StandardCharsets.UTF_8))) {
            for (String line; (line = r.readLine()) != null;) sb.append(line);
        }
        c.disconnect();
        if (code < 200 || code >= 300) throw new IllegalStateException("Groww HTTP " + code + " " + sb);
        return sb.length() == 0 ? new JSONObject() : new JSONObject(sb.toString());
    }

    private static double numberAny(JSONObject o, String... keys) {
        for (String k : keys) if (o.has(k)) { Object v=o.opt(k); if(v instanceof Number) return ((Number)v).doubleValue(); try{return Double.parseDouble(String.valueOf(v));}catch(Exception ignored){} }
        return 0;
    }
    private static Double findNumberByKey(Object node, String key) {
        if (node instanceof JSONObject) {
            JSONObject o=(JSONObject)node;
            if(o.has(key)){Object v=o.opt(key); if(v instanceof Number)return ((Number)v).doubleValue(); try{return Double.parseDouble(String.valueOf(v));}catch(Exception ignored){}}
            Iterator<String> it=o.keys(); while(it.hasNext()){Double d=findNumberByKey(o.opt(it.next()),key); if(d!=null)return d;}
        } else if(node instanceof JSONArray){JSONArray a=(JSONArray)node; for(int i=0;i<a.length();i++){Double d=findNumberByKey(a.opt(i),key);if(d!=null)return d;}}
        return null;
    }
    private static String findStringByKey(Object node,String key){
        if(node instanceof JSONObject){JSONObject o=(JSONObject)node;if(o.has(key)){Object v=o.opt(key);if(v!=null&&v!=JSONObject.NULL)return String.valueOf(v);}Iterator<String>it=o.keys();while(it.hasNext()){String s=findStringByKey(o.opt(it.next()),key);if(s!=null)return s;}}
        else if(node instanceof JSONArray){JSONArray a=(JSONArray)node;for(int i=0;i<a.length();i++){String s=findStringByKey(a.opt(i),key);if(s!=null)return s;}}return null;
    }
    private static JSONObject findObjectForSymbol(Object node,String symbol){
        if(node instanceof JSONObject){JSONObject o=(JSONObject)node;String s=o.optString("trading_symbol",o.optString("symbol",""));if(symbol.equalsIgnoreCase(s))return o;Iterator<String>it=o.keys();while(it.hasNext()){JSONObject p=findObjectForSymbol(o.opt(it.next()),symbol);if(p!=null)return p;}}
        else if(node instanceof JSONArray){JSONArray a=(JSONArray)node;for(int i=0;i<a.length();i++){JSONObject p=findObjectForSymbol(a.opt(i),symbol);if(p!=null)return p;}}return null;
    }
}

final class Call {
    final String symbol; final double target, entryLow, entryHigh, multyfiStop;
    Call(String symbol,double target,double entryLow,double entryHigh,double stop){this.symbol=symbol;this.target=target;this.entryLow=entryLow;this.entryHigh=entryHigh;this.multyfiStop=stop;}
}
final class Position { final int quantity; final double avgPrice; Position(int q,double a){quantity=q;avgPrice=a;} }
final class Telemetry {
    long notificationPostWallMs, appReceiveElapsedNs, buyDispatchElapsedNs, buyAckElapsedNs, fillWallMs, sellDispatchElapsedNs; String buyOrderId="",sellOrderId="";
    long appDispatchMs(){return appReceiveElapsedNs>0&&buyDispatchElapsedNs>0?TimeUnit.NANOSECONDS.toMillis(buyDispatchElapsedNs-appReceiveElapsedNs):-1;}
}
final class ChargeEstimator {
    static double roundTrip(double buy,double sell){
        double b1=Math.min(20.0,buy*0.001), b2=Math.min(20.0,sell*0.001);
        double txn=(buy+sell)*0.0000297, sebi=(buy+sell)*0.000001, stt=sell*0.00025, stamp=buy*0.00003;
        double gst=(b1+b2+txn+sebi)*0.18;
        return b1+b2+txn+sebi+stt+stamp+gst;
    }
}
