from pathlib import Path
p = Path('app/src/main/java/com/suhas/multyfideliverybuy/GrowwClient.java')
s = p.read_text()
old = '''            Result gtt = createGttTarget(context, instrument.symbol, fill.quantity, product,
                    isLong ? "SELL" : "BUY", isLong ? "UP" : "DOWN", target,
                    makeReference(isLong ? "LGT" : "SHT", instrument.symbol));
            if (!gtt.success) {
                return new ManualResult(true, false, gtt.unknown,
                        "ENTRY EXECUTED • " + instrument.symbol + " • avg ₹" + money(fill.averagePrice)
                                + " • qty " + fill.quantity + ". 1% target ₹" + money(target) + " was NOT created: " + gtt.message);
            }

            String side = isLong ? "LONG CNC BUY" : "SHORT MIS SELL";
            String exit = isLong ? "GTT SELL" : "GTT BUY-to-cover";
            return new ManualResult(true, true, false,
                    side + " EXECUTED • " + instrument.symbol + " • qty " + fill.quantity + " • avg ₹" + money(fill.averagePrice)
                            + " • " + exit + " target ₹" + money(target) + " (1%).");
'''
new = '''            Result targetResult;
            if (isLong) {
                targetResult = createGttTarget(context, instrument.symbol, fill.quantity, "CNC",
                        "SELL", "UP", target, makeReference("LGT", instrument.symbol));
            } else {
                // A short is intraday. Keep its cover as a DAY LIMIT BUY rather than a persistent GTT,
                // so an unfilled target cannot survive the MIS position into a later session.
                targetResult = submitShortCoverLimit(context, instrument.symbol, fill.quantity, target,
                        makeReference("SHT", instrument.symbol));
            }
            if (!targetResult.success) {
                return new ManualResult(true, false, targetResult.unknown,
                        "ENTRY EXECUTED • " + instrument.symbol + " • avg ₹" + money(fill.averagePrice)
                                + " • qty " + fill.quantity + ". 1% target ₹" + money(target) + " was NOT created: " + targetResult.message);
            }

            String side = isLong ? "LONG CNC BUY" : "SHORT MIS SELL";
            String exit = isLong ? "GTT SELL" : "DAY LIMIT BUY-to-cover";
            return new ManualResult(true, true, false,
                    side + " EXECUTED • " + instrument.symbol + " • qty " + fill.quantity + " • avg ₹" + money(fill.averagePrice)
                            + " • " + exit + " target ₹" + money(target) + " (1%).");
'''
if old not in s:
    raise SystemExit('trade target block not found')
s = s.replace(old, new, 1)
marker = '''    private static Result createGttTarget(Context context, String symbol, int quantity, String product,
'''
insert = '''    private static Result submitShortCoverLimit(Context context, String symbol, int quantity, double target, String referenceId) {
        try {
            JSONObject body = new JSONObject();
            body.put("trading_symbol", symbol);
            body.put("quantity", quantity);
            body.put("validity", "DAY");
            body.put("exchange", "NSE");
            body.put("segment", "CASH");
            body.put("product", "MIS");
            body.put("order_type", "LIMIT");
            body.put("price", money(target));
            body.put("transaction_type", "BUY");
            body.put("order_reference_id", referenceId);

            HttpResponse r = post(ORDER_URL, ensureToken(context), body.toString(), true);
            if (r.code == 401 || r.code == 403) {
                AppPrefs.clearAccessToken(context);
                Result a = authenticate(context);
                if (!a.success) return a;
                r = post(ORDER_URL, AppPrefs.getAccessToken(context), body.toString(), true);
            }
            if (r.code >= 200 && r.code < 300) {
                String id = "";
                try {
                    JSONObject json = new JSONObject(r.body);
                    JSONObject payload = json.optJSONObject("payload");
                    if (payload != null) id = payload.optString("groww_order_id", "");
                } catch (Exception ignored) {}
                return new Result(true, false, r.code, "DAY LIMIT BUY-to-cover target active" + (id.isEmpty() ? "" : " • " + id));
            }
            return new Result(false, false, r.code, "Short cover target rejected (HTTP " + r.code + "): " + shortText(r.body));
        } catch (SocketTimeoutException e) {
            return new Result(false, true, 0, "Short cover target status unknown after timeout. Verify Orders in Groww; no automatic retry was made.");
        } catch (Exception e) {
            return new Result(false, true, 0, "Short cover target status unknown after network error: " + safeMessage(e) + ". Verify Groww before retrying.");
        }
    }

'''
if marker not in s:
    raise SystemExit('insert marker not found')
s = s.replace(marker, insert + marker, 1)
p.write_text(s)
