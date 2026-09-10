from pathlib import Path

root = Path.cwd()
j = root / 'app/src/main/java/com/suhas/multyfideliverybuy'

# Version bump.
p = root / 'app/build.gradle'
s = p.read_text()
s = s.replace('versionCode 142', 'versionCode 143')
s = s.replace("versionName '1.4.2'", "versionName '1.4.3'")
p.write_text(s)

# Univest averaging ladder: fixed ₹5,000 adds at -2%, -4%, -6% from original anchor.
p = j / 'UnivestManager.java'
s = p.read_text()
s = s.replace('private static final double[] AVERAGE_DROPS = {0.03, 0.06, 0.09};',
              'private static final double[] AVERAGE_DROPS = {0.02, 0.04, 0.06};')
s = s.replace('(nextLevel * 3) + "% below original entry', '(nextLevel * 2) + "% below original entry')
s = s.replace('(nextLevel * 3) + "%, ₹5,000)', '(nextLevel * 2) + "%, ₹5,000)')

# Official exit: freeze new exposure, cancel tracked Univest GTT, clear conflicting regular CNC SELL orders,
# reconcile actual broker CNC quantity, then sell only the remaining tracked quantity.
old = '''        state.phase = UnivestStateStore.EXITING_OFFICIAL;\n        state.exitRequestedQty = state.quantity;\n        state.lastAction = "Official Univest exit received; MARKET SELL dispatch starting.";\n        UnivestStateStore.put(context, state);\n\n        GrowwClient.ExecutionResult sell = GrowwClient.placeUnivestCncMarketSell(\n                context, symbol, state.exitRequestedQty, ref("UVX", symbol));\n        long sourceAgeAtDispatch = sell.dispatchAtMillis > 0 && notificationPostTime > 0\n                ? Math.max(0L, sell.dispatchAtMillis - notificationPostTime) : -1L;\n\n        // Once the authoritative exit is submitted/rejected, never leave an averaging/re-entry GTT able to add exposure.\n        cancelTrackedGtt(context, state);\n\n        if (!sell.submitted) {\n            state.phase = UnivestStateStore.ERROR;\n            state.lastAction = "Official exit SELL not submitted: " + sell.message;\n            UnivestStateStore.put(context, state);\n            status(context, "UNIVEST EXIT FAILED • " + symbol + age(sourceAgeAtDispatch) + " • " + sell.message\n                    + " • Univest averaging/re-entry GTT cancelled.");\n            return;\n        }\n'''
new = '''        state.phase = UnivestStateStore.EXITING_OFFICIAL;\n        state.exitRequestedQty = 0;\n        state.lastAction = "Official Univest exit received; clearing conflicting sell orders and reconciling remaining CNC quantity.";\n        UnivestStateStore.put(context, state);\n\n        // First freeze any app-owned averaging/re-entry GTT so no new exposure can be added during exit.\n        cancelTrackedGtt(context, state);\n\n        // A user's own pending CNC SELL can reserve shares and make our MARKET SELL fail with\n        // "not enough shares". Clear conflicting regular CASH/CNC SELL orders before exit.\n        GrowwClient.Result cleanup = GrowwClient.cancelOpenCncSellOrdersForSymbol(context, symbol);\n        if (!cleanup.success) {\n            state.phase = UnivestStateStore.ERROR;\n            state.lastAction = "Official exit blocked while clearing conflicting CNC SELL orders: " + cleanup.message;\n            UnivestStateStore.put(context, state);\n            status(context, "UNIVEST EXIT BLOCKED • " + symbol + " • " + cleanup.message\n                    + " • no market sell sent until the conflicting order state is safe.");\n            return;\n        }\n\n        GrowwClient.PositionSnapshot broker = GrowwClient.getCncPosition(context, symbol);\n        if (!broker.success) {\n            state.phase = UnivestStateStore.ERROR;\n            state.lastAction = "Official exit could not reconcile broker CNC quantity: " + broker.message;\n            UnivestStateStore.put(context, state);\n            status(context, "UNIVEST EXIT BLOCKED • " + symbol + " • could not reconcile remaining CNC quantity: " + broker.message);\n            return;\n        }\n\n        int sellQty = Math.min(state.quantity, Math.max(0, broker.quantity));\n        if (sellQty <= 0) {\n            state.phase = UnivestStateStore.EXITED;\n            state.quantity = 0;\n            state.principal = 0;\n            state.estimatedBuyCharges = 0;\n            state.exitOrderId = "";\n            state.exitRequestedQty = 0;\n            state.brokerQtyAfterLastFill = broker.quantity;\n            state.lastAction = "Official Univest exit received; no remaining CNC quantity after sell-order reconciliation.";\n            UnivestStateStore.put(context, state);\n            status(context, "UNIVEST OFFICIAL EXIT COMPLETE • " + symbol + " • NO HOLDING remained after reconciliation • " + cleanup.message);\n            return;\n        }\n\n        state.exitRequestedQty = sellQty;\n        state.lastAction = "Official exit reconciled; MARKET SELL dispatch starting for remaining tracked qty " + sellQty + ". " + cleanup.message;\n        UnivestStateStore.put(context, state);\n\n        GrowwClient.ExecutionResult sell = GrowwClient.placeUnivestCncMarketSell(\n                context, symbol, state.exitRequestedQty, ref("UVX", symbol));\n        long sourceAgeAtDispatch = sell.dispatchAtMillis > 0 && notificationPostTime > 0\n                ? Math.max(0L, sell.dispatchAtMillis - notificationPostTime) : -1L;\n\n        if (!sell.submitted) {\n            state.phase = UnivestStateStore.ERROR;\n            state.lastAction = "Official exit SELL not submitted after reconciliation: " + sell.message;\n            UnivestStateStore.put(context, state);\n            status(context, "UNIVEST EXIT FAILED • " + symbol + age(sourceAgeAtDispatch) + " • " + sell.message\n                    + " • conflicting regular CNC SELL orders were reconciled first.");\n            return;\n        }\n'''
if old not in s:
    raise SystemExit('Official exit block not found')
s = s.replace(old, new)

# Profit capture uses the same pre-sell regular-order reconciliation, so a forgotten manual target cannot block it.
old = '''        state.phase = UnivestStateStore.EXITING_PROFIT;\n        state.exitRequestedQty = state.quantity;\n        state.lastAction = "₹2,500 NET profit capture threshold reached; MARKET SELL dispatch starting. Estimated net at trigger ₹" + money(estimatedNet);\n        UnivestStateStore.put(context, state);\n\n        GrowwClient.ExecutionResult sell = GrowwClient.placeUnivestCncMarketSell(context, state.symbol, state.exitRequestedQty, ref("UVP", state.symbol));\n        cancelTrackedGtt(context, state);\n        if (!sell.submitted) {\n            state.phase = UnivestStateStore.ERROR;\n            state.lastAction = "Profit-capture SELL not submitted: " + sell.message;\n            UnivestStateStore.put(context, state);\n            status(context, "UNIVEST ₹2,500 NET CAPTURE FAILED • " + state.symbol + " • " + sell.message);\n            return;\n        }\n'''
new = '''        state.phase = UnivestStateStore.EXITING_PROFIT;\n        state.exitRequestedQty = 0;\n        state.lastAction = "₹2,500 NET profit capture threshold reached; clearing conflicting sell orders before MARKET SELL. Estimated net at trigger ₹" + money(estimatedNet);\n        UnivestStateStore.put(context, state);\n\n        cancelTrackedGtt(context, state);\n        GrowwClient.Result cleanup = GrowwClient.cancelOpenCncSellOrdersForSymbol(context, state.symbol);\n        if (!cleanup.success) {\n            state.phase = UnivestStateStore.ERROR;\n            state.lastAction = "Profit capture blocked while clearing conflicting CNC SELL orders: " + cleanup.message;\n            UnivestStateStore.put(context, state);\n            status(context, "UNIVEST ₹2,500 NET CAPTURE BLOCKED • " + state.symbol + " • " + cleanup.message);\n            return;\n        }\n\n        GrowwClient.PositionSnapshot broker = GrowwClient.getCncPosition(context, state.symbol);\n        if (!broker.success) {\n            state.phase = UnivestStateStore.ERROR;\n            state.lastAction = "Profit capture could not reconcile broker CNC quantity: " + broker.message;\n            UnivestStateStore.put(context, state);\n            status(context, "UNIVEST ₹2,500 NET CAPTURE BLOCKED • " + state.symbol + " • " + broker.message);\n            return;\n        }\n\n        int sellQty = Math.min(state.quantity, Math.max(0, broker.quantity));\n        if (sellQty <= 0) {\n            state.phase = UnivestStateStore.FLAT_WAIT_EXIT;\n            state.quantity = 0;\n            state.principal = 0;\n            state.estimatedBuyCharges = 0;\n            state.exitOrderId = "";\n            state.exitRequestedQty = 0;\n            state.brokerQtyAfterLastFill = broker.quantity;\n            state.lastAction = "Profit capture found no remaining CNC holding after sell-order reconciliation; staying flat until Univest official exit.";\n            UnivestStateStore.put(context, state);\n            status(context, "UNIVEST PROFIT CAPTURE • " + state.symbol + " • NO HOLDING remained after reconciliation • staying flat until official exit.");\n            return;\n        }\n\n        state.exitRequestedQty = sellQty;\n        UnivestStateStore.put(context, state);\n        GrowwClient.ExecutionResult sell = GrowwClient.placeUnivestCncMarketSell(context, state.symbol, state.exitRequestedQty, ref("UVP", state.symbol));\n        if (!sell.submitted) {\n            state.phase = UnivestStateStore.ERROR;\n            state.lastAction = "Profit-capture SELL not submitted after reconciliation: " + sell.message;\n            UnivestStateStore.put(context, state);\n            status(context, "UNIVEST ₹2,500 NET CAPTURE FAILED • " + state.symbol + " • " + sell.message);\n            return;\n        }\n'''
if old not in s:
    raise SystemExit('Profit capture block not found')
s = s.replace(old, new)
p.write_text(s)

# Groww regular-order reconciliation helpers.
p = j / 'GrowwClient.java'
s = p.read_text()
s = s.replace('    private static final String ORDER_DETAIL_URL = "https://api.groww.in/v1/order/detail/";\n',
              '    private static final String ORDER_DETAIL_URL = "https://api.groww.in/v1/order/detail/";\n    private static final String ORDER_LIST_URL = "https://api.groww.in/v1/order/list";\n    private static final String ORDER_CANCEL_URL = "https://api.groww.in/v1/order/cancel";\n')

insert_before = '''    static PositionSnapshot getCncPosition(Context context, String symbol) {\n'''
if insert_before not in s:
    raise SystemExit('GrowwClient getCncPosition insertion point not found')
helpers = r'''    static boolean shouldCancelCncSellOrder(String wantedSymbol, String orderSymbol, String product,
                                            String transactionType, String orderStatus, int remainingQuantity) {
        if (wantedSymbol == null || orderSymbol == null || !wantedSymbol.equalsIgnoreCase(orderSymbol)) return false;
        if (!"CNC".equalsIgnoreCase(product)) return false;
        if (!"SELL".equalsIgnoreCase(transactionType)) return false;
        if (remainingQuantity <= 0) return false;
        String st = orderStatus == null ? "" : orderStatus.trim().toUpperCase(Locale.US);
        return !("COMPLETED".equals(st) || "EXECUTED".equals(st) || "CANCELLED".equals(st)
                || "REJECTED".equals(st) || "FAILED".equals(st));
    }

    /**
     * Clears regular pending/open CASH/CNC SELL orders for a symbol before an automated Univest market exit.
     * This prevents a user's forgotten manual target order from reserving the same delivery shares.
     * The method re-lists after cancellation and will not report success while a conflicting sell remains.
     */
    static Result cancelOpenCncSellOrdersForSymbol(Context context, String symbol) {
        if (symbol == null || symbol.trim().isEmpty()) return new Result(false, false, 0, "Missing symbol for sell-order reconciliation.");
        String wanted = symbol.trim().toUpperCase(Locale.US);
        try {
            java.util.ArrayList<String> ids = listOpenCncSellOrderIds(context, wanted);
            if (ids.isEmpty()) return new Result(true, false, 200, "No conflicting open CNC SELL orders found.");

            boolean sawUnknown = false;
            for (String id : ids) {
                try {
                    JSONObject body = new JSONObject();
                    body.put("segment", "CASH");
                    body.put("groww_order_id", id);
                    HttpResponse r = post(ORDER_CANCEL_URL, ensureToken(context), body.toString(), true);
                    if (r.code == 401 || r.code == 403) {
                        AppPrefs.clearAccessToken(context);
                        Result auth = authenticate(context);
                        if (!auth.success) return auth;
                        r = post(ORDER_CANCEL_URL, AppPrefs.getAccessToken(context), body.toString(), true);
                    }
                    if (!(r.code >= 200 && r.code < 300)) {
                        // Do not immediately assume failure: the order may have completed/cancelled during the race.
                        // A final re-list below is authoritative for whether a conflict still exists.
                    }
                } catch (SocketTimeoutException e) {
                    sawUnknown = true;
                }
            }

            java.util.ArrayList<String> remaining = listOpenCncSellOrderIds(context, wanted);
            if (!remaining.isEmpty()) {
                return new Result(false, sawUnknown, 0,
                        "Conflicting CNC SELL order(s) still active after cancellation attempt: " + remaining.size() + ".");
            }
            return new Result(true, sawUnknown, 200,
                    "Cleared " + ids.size() + " conflicting open CNC SELL order(s) before automated exit.");
        } catch (SocketTimeoutException e) {
            return new Result(false, true, 0, "Sell-order reconciliation timed out; no automated market sell was sent.");
        } catch (Exception e) {
            return new Result(false, true, 0, "Sell-order reconciliation failed: " + safeMessage(e));
        }
    }

    private static java.util.ArrayList<String> listOpenCncSellOrderIds(Context context, String wantedSymbol) throws Exception {
        java.util.ArrayList<String> out = new java.util.ArrayList<>();
        for (int page = 0; page < 5; page++) {
            String endpoint = ORDER_LIST_URL + "?segment=CASH&page=" + page + "&page_size=100";
            HttpResponse r = get(endpoint, ensureToken(context), true);
            if (r.code == 401 || r.code == 403) {
                AppPrefs.clearAccessToken(context);
                Result auth = authenticate(context);
                if (!auth.success) throw new IllegalStateException(auth.message);
                r = get(endpoint, AppPrefs.getAccessToken(context), true);
            }
            if (!(r.code >= 200 && r.code < 300)) {
                throw new IllegalStateException("Order list HTTP " + r.code + ": " + shortText(r.body));
            }
            JSONObject root = new JSONObject(r.body);
            JSONObject payload = root.optJSONObject("payload");
            JSONArray list = payload == null ? null : payload.optJSONArray("order_list");
            if (list == null || list.length() == 0) break;
            for (int i = 0; i < list.length(); i++) {
                JSONObject o = list.optJSONObject(i);
                if (o == null) continue;
                int remaining = o.optInt("remaining_quantity",
                        Math.max(0, o.optInt("quantity", 0) - o.optInt("filled_quantity", 0)));
                if (shouldCancelCncSellOrder(wantedSymbol,
                        o.optString("trading_symbol", ""),
                        o.optString("product", ""),
                        o.optString("transaction_type", ""),
                        o.optString("order_status", ""),
                        remaining)) {
                    String id = o.optString("groww_order_id", "");
                    if (!id.isEmpty() && !out.contains(id)) out.add(id);
                }
            }
            if (list.length() < 100) break;
        }
        return out;
    }

'''
s = s.replace(insert_before, helpers + insert_before)
p.write_text(s)

# Unit tests for new averaging ladder and sell-order conflict filter.
p = root / 'app/src/test/java/com/suhas/multyfideliverybuy/UnivestStrategyContractTest.java'
s = p.read_text()
insert = r'''
    @org.junit.Test
    public void conflictingRegularCncSellOrderFilterIsNarrow() {
        org.junit.Assert.assertTrue(GrowwClient.shouldCancelCncSellOrder("ANDHRAPAP", "ANDHRAPAP", "CNC", "SELL", "OPEN", 281));
        org.junit.Assert.assertTrue(GrowwClient.shouldCancelCncSellOrder("ANDHRAPAP", "ANDHRAPAP", "CNC", "SELL", "PENDING", 281));
        org.junit.Assert.assertFalse(GrowwClient.shouldCancelCncSellOrder("ANDHRAPAP", "ANDHRAPAP", "CNC", "BUY", "OPEN", 281));
        org.junit.Assert.assertFalse(GrowwClient.shouldCancelCncSellOrder("ANDHRAPAP", "ANDHRAPAP", "MIS", "SELL", "OPEN", 281));
        org.junit.Assert.assertFalse(GrowwClient.shouldCancelCncSellOrder("ANDHRAPAP", "OTHER", "CNC", "SELL", "OPEN", 281));
        org.junit.Assert.assertFalse(GrowwClient.shouldCancelCncSellOrder("ANDHRAPAP", "ANDHRAPAP", "CNC", "SELL", "COMPLETED", 281));
        org.junit.Assert.assertFalse(GrowwClient.shouldCancelCncSellOrder("ANDHRAPAP", "ANDHRAPAP", "CNC", "SELL", "OPEN", 0));
    }
'''
idx = s.rfind('}')
if idx < 0:
    raise SystemExit('UnivestStrategyContractTest closing brace not found')
s = s[:idx] + insert + s[idx:]
p.write_text(s)

# UI wording.
p = j / 'MainActivity.java'
s = p.read_text()
s = s.replace('v1.4.2  •  DELIVERY FIRST', 'v1.4.3  •  DELIVERY FIRST')
s = s.replace('v1.4.2 • Delivery Trade Hub', 'v1.4.3 • Delivery Trade Hub')
s = s.replace('₹5,000 at −3% / −6% / −9%', '₹5,000 at −2% / −4% / −6%')
s = s.replace('one broker-hosted ₹5,000 CNC BUY GTT at a time at −3%, then −6%, then −9% from the original executed entry.',
              'one broker-hosted ₹5,000 CNC BUY GTT at a time at −2%, then −4%, then −6% from the original executed entry.')
s = s.replace('Univest Profit Booked / close is authoritative: sell the tracked CNC quantity and clean Univest GTTs.',
              'Univest Profit Booked / close is authoritative: cancel tracked averaging/re-entry GTTs, clear conflicting open/pending regular CNC SELL orders for that symbol, reconcile remaining broker CNC quantity, then sell the remaining tracked CNC quantity.')
p.write_text(s)

# Static contract validation.
p = root / 'scripts/validate_contract.py'
s = p.read_text()
s = s.replace("'version 1.4.2':\"versionName '1.4.2'\" in gradle and 'versionCode 142' in gradle,",
              "'version 1.4.3':\"versionName '1.4.3'\" in gradle and 'versionCode 143' in gradle,")
s = s.replace("'Univest averaging 3 6 9':'{0.03, 0.06, 0.09}' in univest,",
              "'Univest averaging 2 4 6':'{0.02, 0.04, 0.06}' in univest,")
marker = " 'Univest always CNC delivery':'placeUnivestCncMarketBuy' in groww and 'submitMarketOrder(context, symbol, quantity, \"CNC\", \"BUY\"' in groww and 'placeUnivestCncMarketSell' in groww,\n"
extra = " 'Univest regular sell conflict reconciliation':'/v1/order/list' in groww and '/v1/order/cancel' in groww and 'cancelOpenCncSellOrdersForSymbol' in groww and 'shouldCancelCncSellOrder' in groww and 'Math.min(state.quantity, Math.max(0, broker.quantity))' in univest,\n"
if marker not in s:
    raise SystemExit('validator Univest CNC marker not found')
s = s.replace(marker, marker + extra)
p.write_text(s)

# README release notes and locked strategy text.
p = root / 'README.md'
s = p.read_text()
s = s.replace('# Delivery Trade Hub — v1.4.2', '# Delivery Trade Hub — v1.4.3')
s = s.replace('₹5,000 at −3%, then after fill confirmation ₹5,000 at −6%, then ₹5,000 at −9%',
              '₹5,000 at −2%, then after fill confirmation ₹5,000 at −4%, then ₹5,000 at −6%')
s = s.replace('₹5,000 at −3%, −6%, −9% from original executed entry',
              '₹5,000 at −2%, −4%, −6% from original executed entry')
s += '''\n\n## v1.4.3 — Univest 2% averaging + safe delivery-exit reconciliation\n\n- Univest downward averaging is now fixed at ₹5,000 at −2%, −4% and −6% from the original executed entry anchor, one GTT at a time.\n- Before an automated Univest CNC MARKET SELL (official close or ₹2,500 NET capture), the app first cancels its tracked averaging/re-entry GTT, then clears any conflicting regular open/pending CASH/CNC SELL orders for that same symbol.\n- The app re-lists orders after cancellation; if a conflicting sell is still active or cancellation state is uncertain, it does not send the market sell.\n- After cleanup, the app fetches the current broker CNC position and sells only min(tracked Univest quantity, remaining broker CNC quantity). This avoids the prior \"not enough shares\" failure when a manual delivery sell order had reserved the shares.\n- Univest remains 1–3 month equity entries only and always CASH/CNC DELIVERY; recommendation-cycle dedupe from v1.4.2 remains unchanged.\n'''
p.write_text(s)

print('Applied Delivery Trade Hub v1.4.3 Univest averaging and exit reconciliation')
