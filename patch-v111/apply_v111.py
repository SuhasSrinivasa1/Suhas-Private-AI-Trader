from pathlib import Path

root = Path(__file__).resolve().parents[1] if Path(__file__).parent.name == 'patch-v111' else Path.cwd()
# In CI this script is copied/run from repository patch-v111 but edits ./fresh-delivery-buy when passed by cwd.
if (Path.cwd() / 'app').exists():
    root = Path.cwd()

net_target = r'''package com.suhas.multyfideliverybuy;

/**
 * Conservative NSE equity-delivery charge estimator used only to set a broker-hosted GTT target.
 * Rates reflect Groww's published delivery pricing as checked on 2026-09-02.
 * The target is rounded upward to the instrument tick so estimated net profit is at least 1% of buy value.
 */
final class DeliveryNetTarget {
    private static final double BROKERAGE_RATE = 0.001;
    private static final double BROKERAGE_CAP = 20.0;
    private static final double BROKERAGE_MIN = 5.0;
    private static final double STT_DELIVERY = 0.001;
    private static final double STAMP_BUY = 0.00015;
    private static final double NSE_TXN = 0.0000297;
    private static final double SEBI = 0.000001;
    private static final double IPFT = 0.000001;
    private static final double GST = 0.18;
    private static final double DP_SELL_BASE = 20.0;
    private static final double ROUNDING_SAFETY = 2.0;

    private DeliveryNetTarget() {}

    static double targetPrice(double averageBuyPrice, int quantity, double tickSize) {
        if (!(averageBuyPrice > 0) || quantity <= 0) return 0.0;
        double buyValue = averageBuyPrice * quantity;
        double desiredNetProfit = buyValue * 0.01;
        double buyCharges = buyCharges(buyValue);
        double sellValue = buyValue + desiredNetProfit + buyCharges + sellCharges(buyValue * 1.02) + ROUNDING_SAFETY;
        for (int i = 0; i < 12; i++) {
            sellValue = buyValue + desiredNetProfit + buyCharges + sellCharges(sellValue) + ROUNDING_SAFETY;
        }
        double tick = tickSize > 0 ? tickSize : 0.05;
        double target = Math.ceil((sellValue / quantity) / tick - 1e-9) * tick;
        target = Math.round(target * 10000.0) / 10000.0;
        int guard = 0;
        while (estimatedNetProfit(averageBuyPrice, quantity, target) + 1e-7 < desiredNetProfit && guard++ < 1000) {
            target = Math.round((target + tick) * 10000.0) / 10000.0;
        }
        return target;
    }

    static double estimatedNetProfit(double averageBuyPrice, int quantity, double sellPrice) {
        if (!(averageBuyPrice > 0) || !(sellPrice > 0) || quantity <= 0) return Double.NEGATIVE_INFINITY;
        double buyValue = averageBuyPrice * quantity;
        double sellValue = sellPrice * quantity;
        return sellValue - buyValue - buyCharges(buyValue) - sellCharges(sellValue);
    }

    static double buyCharges(double value) {
        double brokerage = brokerage(value);
        double exchange = value * NSE_TXN;
        double sebi = value * SEBI;
        double ipft = value * IPFT;
        double gst = GST * (brokerage + exchange + sebi + ipft);
        return brokerage + (value * STT_DELIVERY) + (value * STAMP_BUY) + exchange + sebi + ipft + gst;
    }

    static double sellCharges(double value) {
        double brokerage = brokerage(value);
        double exchange = value * NSE_TXN;
        double sebi = value * SEBI;
        double ipft = value * IPFT;
        double dp = value >= 100.0 ? DP_SELL_BASE : 3.50;
        double gst = GST * (brokerage + exchange + sebi + ipft + dp);
        return brokerage + (value * STT_DELIVERY) + exchange + sebi + ipft + dp + gst;
    }

    private static double brokerage(double value) {
        if (!(value > 0)) return 0.0;
        double raw = Math.min(BROKERAGE_CAP, value * BROKERAGE_RATE);
        if (raw >= BROKERAGE_MIN) return raw;
        return Math.min(BROKERAGE_MIN, value * 0.025);
    }
}
'''

net_test = r'''package com.suhas.multyfideliverybuy;

import org.junit.Test;
import static org.junit.Assert.*;

public class DeliveryNetTargetTest {
    @Test public void targetClearsOnePercentNetForTypicalOneLakhBuy() {
        double avg = 500.0;
        int qty = 200;
        double target = DeliveryNetTarget.targetPrice(avg, qty, 0.05);
        double net = DeliveryNetTarget.estimatedNetProfit(avg, qty, target);
        assertTrue(target > avg * 1.01);
        assertTrue(net >= avg * qty * 0.01);
    }

    @Test public void targetUsesActualFillAndTick() {
        double avg = 1704.43;
        int qty = 58;
        double target = DeliveryNetTarget.targetPrice(avg, qty, 0.05);
        double units = target / 0.05;
        assertEquals(Math.rint(units), units, 1e-7);
        assertTrue(DeliveryNetTarget.estimatedNetProfit(avg, qty, target) >= avg * qty * 0.01);
    }
}
'''

java_dir = root / 'app/src/main/java/com/suhas/multyfideliverybuy'
test_dir = root / 'app/src/test/java/com/suhas/multyfideliverybuy'
java_dir.mkdir(parents=True, exist_ok=True)
test_dir.mkdir(parents=True, exist_ok=True)
(java_dir / 'DeliveryNetTarget.java').write_text(net_target)
(test_dir / 'DeliveryNetTargetTest.java').write_text(net_test)

# Groww client: keep entry submission identical, add only post-fill target creation.
p = java_dir / 'GrowwClient.java'
s = p.read_text()
old = '''    static Result placeDeliveryMarketBuy(Context context, String symbol, int quantity, String referenceId) {
        OrderSubmit s = submitMarketOrder(context, symbol, quantity, "CNC", "BUY", referenceId);
        return new Result(s.success, s.unknown, s.code, s.message);
    }
'''
new = '''    static Result placeDeliveryMarketBuy(Context context, String symbol, int quantity, String referenceId) {
        OrderSubmit s = submitMarketOrder(context, symbol, quantity, "CNC", "BUY", referenceId);
        return new Result(s.success, s.unknown, s.code, s.message);
    }

    /**
     * Multyfi INTRADAY path: the BUY submission is intentionally identical to placeDeliveryMarketBuy.
     * Only after Groww accepts and fills the CNC MARKET BUY do we calculate a 1% NET-profit target
     * and create a broker-hosted GTT SELL. No LTP lookup or price watcher is added to the hot path.
     */
    static ManualResult placeDeliveryMarketBuyWithNetGtt(Context context, String symbol, int quantity, String referenceId) {
        OrderSubmit entry = submitMarketOrder(context, symbol, quantity, "CNC", "BUY", referenceId);
        if (!entry.success) {
            return new ManualResult(false, false, entry.unknown, entry.message);
        }
        if (entry.orderId.isEmpty()) {
            return new ManualResult(true, false, false,
                    "CNC MARKET BUY accepted for " + symbol + " qty " + quantity
                            + ", but Groww returned no order ID. Net 1% GTT was NOT created; verify manually.");
        }
        try {
            Fill fill = awaitExecution(context, entry.orderId, quantity);
            if (fill.quantity < 1 || !(fill.averagePrice > 0)) {
                return new ManualResult(true, false, false,
                        "CNC MARKET BUY accepted • " + symbol + " • qty " + quantity + " • order " + entry.orderId
                                + ". Fill price was not confirmed in time, so net 1% GTT was NOT created; verify Groww manually.");
            }

            double tick = 0.05;
            try {
                InstrumentRepository.Instrument instrument = InstrumentRepository.resolve(InstrumentRepository.load(context), symbol);
                if (instrument != null && instrument.tickSize > 0) tick = instrument.tickSize;
            } catch (Exception ignored) {}

            double target = DeliveryNetTarget.targetPrice(fill.averagePrice, fill.quantity, tick);
            Result gtt = createGttTarget(context, symbol, fill.quantity, "CNC", "SELL", "UP", target,
                    makeReference("MGT", symbol));
            double estimatedNet = DeliveryNetTarget.estimatedNetProfit(fill.averagePrice, fill.quantity, target);
            double buyValue = fill.averagePrice * fill.quantity;
            double netPct = buyValue > 0 ? (estimatedNet / buyValue) * 100.0 : 0.0;
            if (!gtt.success) {
                return new ManualResult(true, false, gtt.unknown,
                        "BUY EXECUTED • " + symbol + " • qty " + fill.quantity + " • avg ₹" + money(fill.averagePrice)
                                + ". Net 1% GTT ₹" + money(target) + " was NOT created: " + gtt.message);
            }
            return new ManualResult(true, true, false,
                    "BUY EXECUTED • " + symbol + " • qty " + fill.quantity + " • avg ₹" + money(fill.averagePrice)
                            + " • GTT SELL ₹" + money(target) + " • estimated net " + String.format(Locale.US, "%.2f", netPct) + "%.");
        } catch (SocketTimeoutException e) {
            return new ManualResult(true, false, true,
                    "BUY was accepted, but fill/GTT confirmation timed out. Check Groww Orders and Smart Orders; no duplicate target retry was made.");
        } catch (Exception e) {
            return new ManualResult(true, false, true,
                    "BUY was accepted, but net 1% GTT status is uncertain: " + safeMessage(e) + ". Check Groww Smart Orders before retrying.");
        }
    }
'''
if old not in s:
    raise SystemExit('GrowwClient base block not found')
s = s.replace(old, new)
p.write_text(s)

# Notification service: only Multyfi INTRADAY gets the new post-buy GTT. Swing/Multibagger stay unchanged.
p = java_dir / 'MultyfiNotificationService.java'
s = p.read_text()
old = '''        executor.execute(() -> {
            GrowwClient.Result r = GrowwClient.placeDeliveryMarketBuy(
                    getApplicationContext(), call.symbol, quantity, ref);
            String prefix = r.success ? "BUY SUBMITTED" : (r.unknown ? "BUY STATUS UNKNOWN" : "BUY NOT SUBMITTED");
            String msg = prefix + " • " + call.category + " • " + call.symbol + " • qty " + quantity + " • " + r.message;
            setStatus(msg);
            showLocalStatus(prefix, msg, r.success);
        });
'''
new = '''        executor.execute(() -> {
            if (call.category == CallParser.Category.INTRADAY) {
                GrowwClient.ManualResult r = GrowwClient.placeDeliveryMarketBuyWithNetGtt(
                        getApplicationContext(), call.symbol, quantity, ref);
                String prefix = r.entrySubmitted
                        ? (r.targetSubmitted ? "BUY + NET 1% GTT READY" : (r.unknown ? "BUY/GTT STATUS CHECK" : "BUY DONE — GTT CHECK"))
                        : (r.unknown ? "BUY STATUS UNKNOWN" : "BUY NOT SUBMITTED");
                String msg = prefix + " • INTRADAY • " + call.symbol + " • qty " + quantity + " • " + r.message;
                setStatus(msg);
                showLocalStatus(prefix, msg, r.entrySubmitted);
            } else {
                GrowwClient.Result r = GrowwClient.placeDeliveryMarketBuy(
                        getApplicationContext(), call.symbol, quantity, ref);
                String prefix = r.success ? "BUY SUBMITTED" : (r.unknown ? "BUY STATUS UNKNOWN" : "BUY NOT SUBMITTED");
                String msg = prefix + " • " + call.category + " • " + call.symbol + " • qty " + quantity + " • " + r.message;
                setStatus(msg);
                showLocalStatus(prefix, msg, r.success);
            }
        });
'''
if old not in s:
    raise SystemExit('Notification service base block not found')
s = s.replace(old, new)
p.write_text(s)

# Version bump.
p = root / 'app/build.gradle'
s = p.read_text().replace('versionCode 110', 'versionCode 111').replace("versionName '1.1.0'", "versionName '1.1.1'")
p.write_text(s)

# Validation contract bump + new locked rules.
p = root / 'scripts/validate_contract.py'
s = p.read_text()
s = s.replace("'version 1.1.0': \"versionName '1.1.0'\" in gradle and 'versionCode 110' in gradle,",
              "'version 1.1.1': \"versionName '1.1.1'\" in gradle and 'versionCode 111' in gradle,")
s = s.replace("'Multyfi auto path remains BUY only': 'placeDeliveryMarketBuy' in service and '\"SELL\"' not in service and '\"MIS\"' not in service,",
              "'Multyfi auto entry remains CNC MARKET BUY': 'placeDeliveryMarketBuyWithNetGtt' in service and 'submitMarketOrder(context, symbol, quantity, \"CNC\", \"BUY\"' in java and '\"MIS\"' not in service,")
needle = "    'Multyfi budget unchanged': '== CallParser.Category.INTRADAY ? 100000 : 10000' in service,\n"
extra = """    'Multyfi intraday gets broker GTT': 'call.category == CallParser.Category.INTRADAY' in service and 'placeDeliveryMarketBuyWithNetGtt' in service and 'createGttTarget(context, symbol, fill.quantity, \"CNC\", \"SELL\", \"UP\"' in java,\n    'Multyfi net target uses charge estimator': 'DeliveryNetTarget.targetPrice' in java and (root / 'app/src/main/java/com/suhas/multyfideliverybuy/DeliveryNetTarget.java').exists(),\n    'Multyfi buy hot path has no LTP': 'placeDeliveryMarketBuyWithNetGtt' in java and 'getLtp(context, symbol)' not in java,\n"""
if needle not in s:
    raise SystemExit('validation insertion point missing')
s = s.replace(needle, needle + extra)
p.write_text(s)

# Release documentation.
p = root / 'README.md'
s = p.read_text().replace('# Multyfi Delivery Buy — v1.1.0', '# Multyfi Delivery Buy — v1.1.1')
s += r'''

## v1.1.1 — Multyfi Intraday net-1% GTT

- The Multyfi INTRADAY entry logic is unchanged: ₹1,00,000 nominal budget → immediate `NSE / CASH / CNC / MARKET / BUY` using the notification price only for quantity sizing.
- After Groww accepts the order, the app briefly polls only order-detail to get the actual fill quantity and average fill price.
- It estimates current Groww/NSE delivery buy+sell charges, including conservative delivery DP sell charges, and calculates the GTT price required for **at least 1.00% net profit on executed buy value** after those estimated charges.
- Because charges exist, the gross price target will normally be a little above +1%.
- The target is rounded upward to the official instrument tick size and stored as a Groww-hosted `CNC / SELL / UP / LIMIT` GTT.
- No LTP lookup, price monitoring, stop-loss, trailing, re-entry, Multyfi-close reaction, position polling, holdings polling, cancel, or modify logic is added to the Multyfi hot path.
- Swing and Multibagger notification BUY behavior remains unchanged in v1.1.1.
'''
p.write_text(s)

print('Applied Multyfi Delivery Buy v1.1.1 net-1% GTT patch')
