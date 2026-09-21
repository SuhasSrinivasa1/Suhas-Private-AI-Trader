from pathlib import Path

root = Path.cwd()
j = root / 'app/src/main/java/com/suhas/multyfideliverybuy'

def replace(path, old, new, label):
    p = Path(path)
    s = p.read_text()
    if old not in s:
        raise SystemExit("Expected block not found: " + label)
    p.write_text(s.replace(old, new))

replace(root/'app/build.gradle', "versionCode 147", "versionCode 148", "versionCode")
replace(root/'app/build.gradle', "versionName '1.4.7'", "versionName '1.4.8'", "versionName")

p = j/'UnivestParser.java'
s = p.read_text()
s = s.replace('enum Type { ENTRY, EXIT }', 'enum Type { ENTRY, ENTRY_RANGE, EXIT }')
needle = '''        if (exit) return new Signal(Type.EXIT, symbol, text);

        boolean entry = containsAny(lower,
'''
insert = '''        if (exit) return new Signal(Type.EXIT, symbol, text);

        boolean entryRange = containsAny(lower,
                "idea back in entry range", "back in entry range");
        if (entryRange) return new Signal(Type.ENTRY_RANGE, symbol, text);

        boolean entry = containsAny(lower,
'''
if needle not in s:
    raise SystemExit('Expected Univest parser exit/entry boundary not found')
s = s.replace(needle, insert)
p.write_text(s)

p = j/'MultyfiNotificationService.java'
s = p.read_text()
old = '''            univestBuyExecutor.execute(() -> {
                UnivestManager.handleEntry(getApplicationContext(), signal, postTime);
                showLocalStatus("UNIVEST EQUITY", AppPrefs.getUnivestStatus(getApplicationContext()), true);
            });
        } else {
            // Do not use a 24-hour raw-text fingerprint for Univest exits. The per-symbol state machine
'''
new = '''            univestBuyExecutor.execute(() -> {
                UnivestManager.handleEntry(getApplicationContext(), signal, postTime);
                showLocalStatus("UNIVEST EQUITY", AppPrefs.getUnivestStatus(getApplicationContext()), true);
            });
        } else if (signal.type == UnivestParser.Type.ENTRY_RANGE) {
            if (!AppPrefs.isReadyForBuy(getApplicationContext())) {
                AppPrefs.setUnivestStatus(getApplicationContext(), "UNIVEST BACK-IN-RANGE IGNORED • " + signal.symbol
                        + " • Groww connection readiness is stale.");
                return;
            }

            UnivestStateStore.State existing = UnivestStateStore.get(getApplicationContext(), signal.symbol);
            if (!UnivestManager.canHandleEntryRange(existing)) {
                String phase = existing == null ? "NOT_TRACKED" : existing.phase;
                AppPrefs.setUnivestStatus(getApplicationContext(), "UNIVEST BACK-IN-RANGE IGNORED • " + signal.symbol
                        + " • no ACTIVE eligible recommendation; current state " + phase + ".");
                return;
            }

            String fp = sha256("URANGE|" + sbn.getKey() + "|" + sbn.getPostTime() + "|" + signal.symbol);
            if (!AppPrefs.claimFingerprint(getApplicationContext(), fp)) {
                AppPrefs.setUnivestStatus(getApplicationContext(), "UNIVEST BACK-IN-RANGE DUPLICATE IGNORED • " + signal.symbol
                        + " • same Android notification instance already handled.");
                return;
            }

            AppPrefs.setUnivestStatus(getApplicationContext(), "UNIVEST BACK IN ENTRY RANGE ACCEPTED • " + signal.symbol
                    + " • additional ₹5,000 CNC DELIVERY BUY starting.");
            univestBuyExecutor.execute(() -> {
                UnivestManager.handleEntryRange(getApplicationContext(), signal, postTime);
                showLocalStatus("UNIVEST ENTRY RANGE", AppPrefs.getUnivestStatus(getApplicationContext()), true);
            });
        } else {
            // Do not use a 24-hour raw-text fingerprint for Univest exits. The per-symbol state machine
'''
if old not in s:
    raise SystemExit('Expected Univest ENTRY->EXIT boundary not found')
s = s.replace(old, new)
p.write_text(s)

p = j/'UnivestManager.java'
s = p.read_text()
s = s.replace('static final int AVERAGE_BUDGET = 5000;',
              'static final int AVERAGE_BUDGET = 5000;\\n    static final int ENTRY_RANGE_BUDGET = 5000;')
marker = '    static void handleExit(Context context, UnivestParser.Signal signal, long notificationPostTime) {'
if marker not in s:
    raise SystemExit('Expected handleExit marker not found')
method = '''    static boolean canHandleEntryRange(UnivestStateStore.State state) {
        return state != null
                && UnivestStateStore.ACTIVE.equals(state.phase)
                && state.quantity > 0;
    }

    static void handleEntryRange(Context context, UnivestParser.Signal signal, long notificationPostTime) {
        if (signal == null || signal.type != UnivestParser.Type.ENTRY_RANGE) return;
        String symbol = signal.symbol.toUpperCase(Locale.US);

        UnivestStateStore.State state = UnivestStateStore.get(context, symbol);
        if (!canHandleEntryRange(state)) {
            String phase = state == null ? "NOT_TRACKED" : state.phase;
            status(context, "UNIVEST BACK-IN-RANGE IGNORED • " + symbol
                    + " • no ACTIVE eligible recommendation; current state " + phase + ".");
            return;
        }

        InstrumentRepository.Instrument instrument = InstrumentRepository.resolve(InstrumentRepository.load(context), symbol);
        if (instrument == null || !instrument.buyAllowed) {
            status(context, "UNIVEST BACK-IN-RANGE BUY SKIPPED • " + symbol
                    + " • Groww NSE CASH instrument is unavailable or buy_allowed=0.");
            return;
        }

        GrowwClient.ExecutionResult add = GrowwClient.placeUnivestCncMarketBuy(
                context, symbol, ENTRY_RANGE_BUDGET, ref("UVB", symbol));
        long sourceAgeAtDispatch = add.dispatchAtMillis > 0 && notificationPostTime > 0
                ? Math.max(0L, add.dispatchAtMillis - notificationPostTime) : -1L;

        if (!add.submitted) {
            status(context, "UNIVEST BACK-IN-RANGE BUY NOT SUBMITTED • " + symbol
                    + age(sourceAgeAtDispatch) + " • " + add.message);
            return;
        }

        if (!add.filled || add.filledQuantity <= 0 || !(add.averagePrice > 0)) {
            state.phase = UnivestStateStore.ERROR;
            state.lastAction = "Back-in-entry-range ₹5,000 CNC BUY accepted but fill not confirmed; no automatic retry. "
                    + add.message;
            UnivestStateStore.put(context, state);
            status(context, "UNIVEST BACK-IN-RANGE BUY ACCEPTED — VERIFY FILL • " + symbol
                    + age(sourceAgeAtDispatch) + " • no automatic retry • " + add.message);
            return;
        }

        double addedValue = add.averagePrice * add.filledQuantity;
        state.quantity += add.filledQuantity;
        state.principal += addedValue;
        state.estimatedBuyCharges += DeliveryNetTarget.buyCharges(addedValue);

        GrowwClient.PositionSnapshot broker = GrowwClient.getCncPosition(context, symbol);
        state.brokerQtyAfterLastFill = broker.success ? broker.quantity : -1;
        state.lastAction = "Idea back in Entry Range • additional ₹5,000 CNC delivery BUY executed"
                + " • qty +" + add.filledQuantity + " • avg ₹" + money(add.averagePrice)
                + " • original anchor retained ₹" + money(state.anchorPrice);
        UnivestStateStore.put(context, state);

        String stop = refreshProtectiveStopAfterFill(context, state);
        String avg = state.activeGttId == null || state.activeGttId.isEmpty()
                ? (UnivestStateStore.ACTIVE.equals(state.phase) ? armNextAverage(context, state) : "averaging blocked")
                : "existing " + state.activeGttKind + " GTT remains active";

        status(context, "UNIVEST BACK IN ENTRY RANGE BUY EXECUTED • " + symbol
                + " • +₹5,000 tranche • qty +" + add.filledQuantity
                + " • avg ₹" + money(add.averagePrice) + age(sourceAgeAtDispatch)
                + " • original anchor unchanged • " + stop + " • " + avg);
    }

'''
s = s.replace(marker, method + marker)
p.write_text(s)

p = j/'MainActivity.java'
s = p.read_text()
s = s.replace('v1.4.7  •  DELIVERY FIRST', 'v1.4.8  •  DELIVERY FIRST')
s = s.replace('v1.4.7 • Delivery Trade Hub', 'v1.4.8 • Delivery Trade Hub')
p.write_text(s)

p = root/'app/src/test/java/com/suhas/multyfideliverybuy/UnivestParserTest.java'
s = p.read_text()
insert = '''
    @org.junit.Test
    public void parsesBackInEntryRangeWithoutDurationAsAddSignal() {
        UnivestParser.Signal s = UnivestParser.parse("Idea back in Entry Range\\nStock: NETWEB\\nView pick details");
        org.junit.Assert.assertNotNull(s);
        org.junit.Assert.assertEquals(UnivestParser.Type.ENTRY_RANGE, s.type);
        org.junit.Assert.assertEquals("NETWEB", s.symbol);
    }

    @org.junit.Test
    public void normalizesBeSuffixForBackInEntryRange() {
        UnivestParser.Signal s = UnivestParser.parse("Idea back in Entry Range\\nStock: HFCL-BE");
        org.junit.Assert.assertNotNull(s);
        org.junit.Assert.assertEquals(UnivestParser.Type.ENTRY_RANGE, s.type);
        org.junit.Assert.assertEquals("HFCL", s.symbol);
    }
'''
pos = s.rfind('}')
if pos < 0:
    raise SystemExit('UnivestParserTest closing brace not found')
s = s[:pos] + insert + s[pos:]
p.write_text(s)

p = root/'app/src/test/java/com/suhas/multyfideliverybuy/UnivestStrategyContractTest.java'
s = p.read_text()
insert = '''
    @org.junit.Test
    public void backInEntryRangeUsesFixedFiveThousandAndOnlyActiveHolding() {
        org.junit.Assert.assertEquals(5000, UnivestManager.ENTRY_RANGE_BUDGET);
        UnivestStateStore.State s = new UnivestStateStore.State();
        s.phase = UnivestStateStore.ACTIVE;
        s.quantity = 4;
        org.junit.Assert.assertTrue(UnivestManager.canHandleEntryRange(s));
        s.phase = UnivestStateStore.EXITED;
        org.junit.Assert.assertFalse(UnivestManager.canHandleEntryRange(s));
        s.phase = UnivestStateStore.ACTIVE;
        s.quantity = 0;
        org.junit.Assert.assertFalse(UnivestManager.canHandleEntryRange(s));
    }
'''
pos = s.rfind('}')
if pos < 0:
    raise SystemExit('UnivestStrategyContractTest closing brace not found')
s = s[:pos] + insert + s[pos:]
p.write_text(s)

p = root/'scripts/validate_contract.py'
s = p.read_text()
s = s.replace("'version 1.4.7':\\\"versionName '1.4.7'\\\" in gradle and 'versionCode 147' in gradle,",
              "'version 1.4.8':\\\"versionName '1.4.8'\\\" in gradle and 'versionCode 148' in gradle,")
needle = " 'Univest averaging fixed 5000':'AVERAGE_BUDGET = 5000' in univest,"
if needle not in s:
    raise SystemExit('Expected Univest averaging validator marker not found')
s = s.replace(needle, needle + """
 'Univest back in entry range fixed 5000':'ENTRY_RANGE_BUDGET = 5000' in univest and 'Type.ENTRY_RANGE' in uparser and 'handleEntryRange' in univest and 'UNIVEST BACK IN ENTRY RANGE ACCEPTED' in service,
 'Univest back range active campaign only':'canHandleEntryRange' in univest and 'UnivestStateStore.ACTIVE.equals(state.phase)' in univest,
 'Univest back range notification instance dedupe':'URANGE|' in service and 'sbn.getKey()' in service and 'sbn.getPostTime()' in service,
""")
p.write_text(s)

p = root/'README.md'
s = p.read_text()
s += '''

## v1.4.8 — Univest Idea back in Entry Range ₹5,000 add

- Recognizes Univest notifications such as Idea back in Entry Range with Stock: NETWEB.
- A distinct Back-in-Entry-Range notification adds a fixed ₹5,000 CNC DELIVERY market buy to an already ACTIVE tracked Univest recommendation.
- The signal itself does not need to repeat the 1-3 month duration; eligibility comes from the already-active recommendation created by a valid 1-3 month New Advisory Pick.
- If the stock is not actively tracked, is already officially EXITED, is flat, or is in an error/exit phase, the Back-in-Entry-Range alert is ignored.
- Duplicate callbacks for the same Android notification instance are suppressed using notification key + post time, while a later genuinely new alert with identical wording may add another ₹5,000.
- The add does not rebase the original entry anchor and does not consume/reset the existing −2/−4/−6/−8% ₹5,000 averaging ladder.
- After a confirmed add, tracked quantity/principal/charges are updated and the −20% protective CNC GTT is resized to the full tracked quantity.
- v1.4.7 Holdings/T1 exit reconciliation fix remains intact.
'''
p.write_text(s)

print('Applied Delivery Trade Hub v1.4.8 Back-in-Entry-Range ₹5,000 add')
