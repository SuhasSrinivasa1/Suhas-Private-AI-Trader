from pathlib import Path

root=Path.cwd(); j=root/'app/src/main/java/com/suhas/multyfideliverybuy'

def rw(path, fn):
    p=Path(path); s=p.read_text(); p.write_text(fn(s))

# Version.
rw(root/'app/build.gradle', lambda s:s.replace('versionCode 147','versionCode 148').replace("versionName '1.4.7'","versionName '1.4.8'"))

# Parser.
p=j/'UnivestParser.java'; s=p.read_text()
s=s.replace('enum Type { ENTRY, EXIT }','enum Type { ENTRY, EXIT, BACK_IN_RANGE }')
needle='''        boolean entry = containsAny(lower,
                "new advisory pick", "new equity pick", "new stock pick", "equity pick", "stock recommendation");
'''
insert='''        boolean backInRange = containsAny(lower,
                "idea back in entry range", "back in entry range");
        if (backInRange) return new Signal(Type.BACK_IN_RANGE, symbol, text);

        boolean entry = containsAny(lower,
                "new advisory pick", "new equity pick", "new stock pick", "equity pick", "stock recommendation");
'''
if needle not in s: raise SystemExit('parser marker missing')
s=s.replace(needle,insert); p.write_text(s)

# Persist two-minute duplicate state.
p=j/'UnivestStateStore.java'; s=p.read_text()
s=s.replace('''        int exitRequestedQty = 0;
        String lastAction = "";
''','''        int exitRequestedQty = 0;
        long lastBackInRangePostTime = 0L;
        String lastBackInRangeHash = "";
        String lastAction = "";
''')
s=s.replace('''                j.put("exitRequestedQty", exitRequestedQty);
                j.put("lastAction", lastAction);
''','''                j.put("exitRequestedQty", exitRequestedQty);
                j.put("lastBackInRangePostTime", lastBackInRangePostTime);
                j.put("lastBackInRangeHash", lastBackInRangeHash);
                j.put("lastAction", lastAction);
''')
s=s.replace('''            s.exitRequestedQty = j.optInt("exitRequestedQty", 0);
            s.lastAction = j.optString("lastAction", "");
''','''            s.exitRequestedQty = j.optInt("exitRequestedQty", 0);
            s.lastBackInRangePostTime = j.optLong("lastBackInRangePostTime", 0L);
            s.lastBackInRangeHash = j.optString("lastBackInRangeHash", "");
            s.lastAction = j.optString("lastAction", "");
''')
p.write_text(s)

# Route Back in Entry Range through the serial Univest BUY executor.
p=j/'MultyfiNotificationService.java'; s=p.read_text()
needle='''        } else {
            // Do not use a 24-hour raw-text fingerprint for Univest exits. The per-symbol state machine
            // already rejects duplicate exits, while allowing a later same-day recommendation cycle to close normally.
            AppPrefs.setUnivestStatus(getApplicationContext(), "UNIVEST OFFICIAL EXIT DETECTED • " + signal.symbol + " • priority CNC MARKET SELL path starting.");
            univestExitExecutor.execute(() -> {
                UnivestManager.handleExit(getApplicationContext(), signal, postTime);
                showLocalStatus("UNIVEST EXIT", AppPrefs.getUnivestStatus(getApplicationContext()), true);
            });
        }
'''
repl='''        } else if (signal.type == UnivestParser.Type.BACK_IN_RANGE) {
            if (!AppPrefs.isReadyForBuy(getApplicationContext())) {
                AppPrefs.setUnivestStatus(getApplicationContext(), "UNIVEST BACK IN RANGE IGNORED • " + signal.symbol
                        + " • Groww connection readiness is stale.");
                return;
            }
            AppPrefs.setUnivestStatus(getApplicationContext(), "UNIVEST BACK IN ENTRY RANGE DETECTED • " + signal.symbol
                    + " • fixed ₹5,000 CNC DELIVERY add/re-entry path starting.");
            univestBuyExecutor.execute(() -> {
                UnivestManager.handleBackInEntryRange(getApplicationContext(), signal, postTime);
                showLocalStatus("UNIVEST BACK IN RANGE", AppPrefs.getUnivestStatus(getApplicationContext()), true);
            });
        } else {
            // Do not use a 24-hour raw-text fingerprint for Univest exits. The per-symbol state machine
            // already rejects duplicate exits, while allowing a later same-day recommendation cycle to close normally.
            AppPrefs.setUnivestStatus(getApplicationContext(), "UNIVEST OFFICIAL EXIT DETECTED • " + signal.symbol + " • priority CNC MARKET SELL path starting.");
            univestExitExecutor.execute(() -> {
                UnivestManager.handleExit(getApplicationContext(), signal, postTime);
                showLocalStatus("UNIVEST EXIT", AppPrefs.getUnivestStatus(getApplicationContext()), true);
            });
        }
'''
if needle not in s: raise SystemExit('service marker missing')
s=s.replace(needle,repl); p.write_text(s)

# Strategy.
p=j/'UnivestManager.java'; s=p.read_text()
s=s.replace('''    static final int AVERAGE_BUDGET = 5000;
    static final double NET_PROFIT_TARGET = 2500.0;
''','''    static final int AVERAGE_BUDGET = 5000;
    static final int BACK_IN_RANGE_BUDGET = 5000;
    static final long BACK_IN_RANGE_DUPLICATE_WINDOW_MS = 120_000L;
    static final double NET_PROFIT_TARGET = 2500.0;
''')
marker='    static void handleExit(Context context, UnivestParser.Signal signal, long notificationPostTime) {'
handler=r'''    static boolean canHandleBackInRangePhase(String phase) {
        return UnivestStateStore.ACTIVE.equals(phase)
                || UnivestStateStore.WAIT_REENTRY.equals(phase)
                || UnivestStateStore.FLAT_WAIT_EXIT.equals(phase);
    }

    static boolean isBackInRangeDuplicate(UnivestStateStore.State state, String rawText, long notificationPostTime) {
        if (state == null) return false;
        long post = notificationPostTime > 0 ? notificationPostTime : System.currentTimeMillis();
        String normalized = rawText == null ? "" : rawText.trim().toLowerCase(Locale.US);
        String hash = Integer.toHexString(normalized.hashCode());
        return !hash.isEmpty() && hash.equals(state.lastBackInRangeHash)
                && state.lastBackInRangePostTime > 0
                && Math.abs(post - state.lastBackInRangePostTime) < BACK_IN_RANGE_DUPLICATE_WINDOW_MS;
    }

    static void handleBackInEntryRange(Context context, UnivestParser.Signal signal, long notificationPostTime) {
        if (signal == null || signal.type != UnivestParser.Type.BACK_IN_RANGE) return;
        String symbol = signal.symbol.toUpperCase(Locale.US);
        UnivestStateStore.State state = UnivestStateStore.get(context, symbol);

        // This follow-up alert inherits eligibility from an already-open 1-3 month equity campaign.
        if (state == null) {
            status(context, "UNIVEST BACK IN RANGE IGNORED • " + symbol + " • no active eligible Univest campaign is tracked.");
            return;
        }
        if (!canHandleBackInRangePhase(state.phase)) {
            status(context, "UNIVEST BACK IN RANGE IGNORED • " + symbol + " • campaign state " + state.phase
                    + " is not eligible for another ₹5,000 buy.");
            return;
        }
        if (isBackInRangeDuplicate(state, signal.rawText, notificationPostTime)) {
            status(context, "UNIVEST BACK IN RANGE DUPLICATE IGNORED • " + symbol + " • same alert already processed recently.");
            return;
        }

        long post = notificationPostTime > 0 ? notificationPostTime : System.currentTimeMillis();
        String normalized = signal.rawText == null ? "" : signal.rawText.trim().toLowerCase(Locale.US);
        state.lastBackInRangePostTime = post;
        state.lastBackInRangeHash = Integer.toHexString(normalized.hashCode());
        state.lastAction = "Back in Entry Range accepted; fixed ₹5,000 CNC delivery buy starting.";
        UnivestStateStore.put(context, state);

        boolean wasFlat = state.quantity <= 0
                || UnivestStateStore.WAIT_REENTRY.equals(state.phase)
                || UnivestStateStore.FLAT_WAIT_EXIT.equals(state.phase);

        // Avoid a double re-entry if profit capture had already armed a REENTRY GTT.
        if (wasFlat && state.activeGttId != null && !state.activeGttId.isEmpty()) {
            GrowwClient.Result cleanup = cancelTrackedGttSafe(context, state);
            if (!cleanup.success) {
                state.phase = UnivestStateStore.ERROR;
                state.lastAction = "Back in Entry Range buy blocked because pending re-entry GTT cancellation is unconfirmed: " + cleanup.message;
                UnivestStateStore.put(context, state);
                status(context, "UNIVEST BACK IN RANGE BLOCKED • " + symbol + " • pending re-entry GTT could not be safely cleared.");
                return;
            }
        }

        GrowwClient.ExecutionResult add = GrowwClient.placeUnivestCncMarketBuy(
                context, symbol, BACK_IN_RANGE_BUDGET, ref("UVB", symbol));
        long sourceAgeAtDispatch = add.dispatchAtMillis > 0 && notificationPostTime > 0
                ? Math.max(0L, add.dispatchAtMillis - notificationPostTime) : -1L;

        if (!add.submitted) {
            state.lastAction = "Back in Entry Range ₹5,000 BUY not submitted. " + add.message;
            UnivestStateStore.put(context, state);
            status(context, "UNIVEST BACK IN RANGE BUY NOT SUBMITTED • " + symbol + age(sourceAgeAtDispatch) + " • " + add.message);
            return;
        }
        if (!add.filled || add.filledQuantity <= 0 || !(add.averagePrice > 0)) {
            state.phase = UnivestStateStore.ERROR;
            state.exitOrderId = add.orderId;
            state.lastAction = "Back in Entry Range CNC BUY accepted but fill not confirmed; verify Groww before any retry. " + add.message;
            UnivestStateStore.put(context, state);
            status(context, "UNIVEST BACK IN RANGE BUY ACCEPTED — VERIFY FILL • " + symbol + age(sourceAgeAtDispatch) + " • " + add.message);
            return;
        }

        double addedValue = add.averagePrice * add.filledQuantity;
        if (wasFlat) {
            state.phase = UnivestStateStore.ACTIVE;
            state.quantity = add.filledQuantity;
            state.principal = addedValue;
            state.estimatedBuyCharges = DeliveryNetTarget.buyCharges(addedValue);
            state.averageLevel = 0;
            state.reentryUsed = true;
        } else {
            state.quantity += add.filledQuantity;
            state.principal += addedValue;
            state.estimatedBuyCharges += DeliveryNetTarget.buyCharges(addedValue);
        }

        GrowwClient.PositionSnapshot broker = GrowwClient.getCncPosition(context, symbol);
        state.brokerQtyAfterLastFill = broker.success ? broker.quantity : -1;
        state.lastAction = "Back in Entry Range fixed ₹5,000 CNC BUY executed • +" + add.filledQuantity
                + " shares @ avg ₹" + money(add.averagePrice) + age(sourceAgeAtDispatch);
        UnivestStateStore.put(context, state);

        String stop = wasFlat ? armProtectiveStop(context, state) : refreshProtectiveStopAfterFill(context, state);
        String average;
        if (!UnivestStateStore.ACTIVE.equals(state.phase)) {
            average = "price averaging blocked until protection is confirmed";
        } else if (wasFlat || state.activeGttId == null || state.activeGttId.isEmpty()) {
            average = armNextAverage(context, state);
        } else {
            average = "existing " + state.activeGttKind + " GTT remains active";
        }
        status(context, "UNIVEST BACK IN ENTRY RANGE BUY EXECUTED • " + symbol + " • ₹5,000 add • +"
                + add.filledQuantity + " shares @ avg ₹" + money(add.averagePrice) + age(sourceAgeAtDispatch)
                + " • " + stop + " • " + average);
    }

'''
if marker not in s: raise SystemExit('manager marker missing')
s=s.replace(marker,handler+marker); p.write_text(s)

# UI + comment.
rw(j/'MainActivity.java',lambda s:s.replace('v1.4.7  •  DELIVERY FIRST','v1.4.8  •  DELIVERY FIRST').replace('v1.4.7 • Delivery Trade Hub','v1.4.8 • Delivery Trade Hub'))
rw(j/'GrowwClient.java',lambda s:s.replace('/** Univest equity fast path: one LTP read only for ₹20k quantity sizing, then immediate CNC MARKET BUY. */','/** Univest equity fast path: one LTP read for budget-based quantity sizing, then immediate CNC MARKET BUY. */'))

# Tests.
p=root/'app/src/test/java/com/suhas/multyfideliverybuy/UnivestParserTest.java'; s=p.read_text(); pos=s.rfind('}')
s=s[:pos]+r'''
    @org.junit.Test public void parsesIdeaBackInEntryRangeWithoutDuration() {
        UnivestParser.Signal s = UnivestParser.parse("Idea back in Entry Range\nStock: NETWEB\nView pick details");
        org.junit.Assert.assertNotNull(s);
        org.junit.Assert.assertEquals(UnivestParser.Type.BACK_IN_RANGE, s.type);
        org.junit.Assert.assertEquals("NETWEB", s.symbol);
    }

    @org.junit.Test public void normalizesBeSuffixForBackInRange() {
        UnivestParser.Signal s = UnivestParser.parse("Idea back in Entry Range\nStock: HFCL-BE");
        org.junit.Assert.assertNotNull(s);
        org.junit.Assert.assertEquals(UnivestParser.Type.BACK_IN_RANGE, s.type);
        org.junit.Assert.assertEquals("HFCL", s.symbol);
    }
'''+s[pos:]; p.write_text(s)

p=root/'app/src/test/java/com/suhas/multyfideliverybuy/UnivestStrategyContractTest.java'; s=p.read_text(); pos=s.rfind('}')
s=s[:pos]+r'''
    @org.junit.Test public void backInRangeBudgetAndEligiblePhasesAreLocked() {
        org.junit.Assert.assertEquals(5000, UnivestManager.BACK_IN_RANGE_BUDGET);
        org.junit.Assert.assertTrue(UnivestManager.canHandleBackInRangePhase(UnivestStateStore.ACTIVE));
        org.junit.Assert.assertTrue(UnivestManager.canHandleBackInRangePhase(UnivestStateStore.WAIT_REENTRY));
        org.junit.Assert.assertTrue(UnivestManager.canHandleBackInRangePhase(UnivestStateStore.FLAT_WAIT_EXIT));
        org.junit.Assert.assertFalse(UnivestManager.canHandleBackInRangePhase(UnivestStateStore.EXITED));
        org.junit.Assert.assertFalse(UnivestManager.canHandleBackInRangePhase(UnivestStateStore.ERROR));
    }

    @org.junit.Test public void backInRangeDuplicateProtectionIsShortWindowOnly() {
        UnivestStateStore.State x = new UnivestStateStore.State();
        x.lastBackInRangeHash = Integer.toHexString("idea back in entry range\nstock: netweb".hashCode());
        x.lastBackInRangePostTime = 1000000L;
        org.junit.Assert.assertTrue(UnivestManager.isBackInRangeDuplicate(x, "Idea back in Entry Range\nStock: NETWEB", 1030000L));
        org.junit.Assert.assertFalse(UnivestManager.isBackInRangeDuplicate(x, "Idea back in Entry Range\nStock: NETWEB", 1180001L));
    }
'''+s[pos:]; p.write_text(s)

# Contract validator.
p=root/'scripts/validate_contract.py'; s=p.read_text()
s=s.replace("'version 1.4.7':\"versionName '1.4.7'\" in gradle and 'versionCode 147' in gradle,","'version 1.4.8':\"versionName '1.4.8'\" in gradle and 'versionCode 148' in gradle,")
marker=" 'Univest holdings T1 reconciliation'"
checks=" 'Univest back in range parser':'BACK_IN_RANGE' in uparser and 'back in entry range' in uparser,\n 'Univest back in range 5000':'BACK_IN_RANGE_BUDGET = 5000' in univest and 'handleBackInEntryRange' in univest and 'fixed ₹5,000 CNC DELIVERY add/re-entry' in service,\n 'Univest back in range active campaign gate':'canHandleBackInRangePhase' in univest and 'no active eligible Univest campaign is tracked' in univest,\n 'Univest back in range short dedupe':'BACK_IN_RANGE_DUPLICATE_WINDOW_MS = 120_000L' in univest and 'lastBackInRangePostTime' in ustate and 'lastBackInRangeHash' in ustate,\n"
if marker not in s: raise SystemExit('validator marker missing')
idx=s.find(marker); s=s[:idx]+checks+s[idx:]; p.write_text(s)

p=root/'README.md'; s=p.read_text()+'''

## v1.4.8 — Univest Back in Entry Range ₹5,000 add
- Recognizes Univest Idea back in Entry Range / Back in Entry Range notifications.
- Only an already-open campaign created from a valid 1–3 month equity recommendation can use this follow-up signal.
- Each genuine Back in Entry Range alert submits one additional fixed ₹5,000 CASH/CNC MARKET BUY.
- This is independent of the existing ₹5,000 averaging ladder at −2%, −4%, −6% and −8% from the original first-fill anchor; the anchor is not rebased.
- After fill, tracked quantity/cost/charges and the −20% protective CNC GTT are updated for the new total quantity.
- When flat after profit capture, any pending automatic REENTRY GTT is cancelled before the immediate ₹5,000 Back-in-Range re-entry.
- Duplicate/reposted copies of the same alert are suppressed for two minutes only; a later genuine alert may add another ₹5,000.
- Closed, exiting, error, or untracked symbols are ignored.
- v1.4.7 Holdings + T1 exit reconciliation remains in place.
'''
p.write_text(s)
print('Applied v1.4.8 Back in Entry Range rule')
