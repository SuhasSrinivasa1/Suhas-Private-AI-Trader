from pathlib import Path

root = Path.cwd()
j = root / 'app/src/main/java/com/suhas/multyfideliverybuy'

# Version bump.
p = root / 'app/build.gradle'
s = p.read_text()
s = s.replace('versionCode 141', 'versionCode 142')
s = s.replace("versionName '1.4.1'", "versionName '1.4.2'")
p.write_text(s)

# Recommendation-cycle-aware Univest entry reservation.
p = j / 'UnivestStateStore.java'
s = p.read_text()
s = s.replace('    static final String ACTIVE = "ACTIVE";\n', '    static final String ENTRY_PENDING = "ENTRY_PENDING";\n    static final String ACTIVE = "ACTIVE";\n')

insert_point = '''    static synchronized State get(Context c, String symbol) {\n        for (State s : all(c)) if (s.symbol.equalsIgnoreCase(symbol)) return s;\n        return null;\n    }\n\n'''
if insert_point not in s:
    raise SystemExit('UnivestStateStore get() insertion point not found')
reservation = '''    static boolean canReservePhase(String phase) {\n        return phase == null || EXITED.equals(phase);\n    }\n\n    static boolean canExecuteReservedPhase(String phase) {\n        return ENTRY_PENDING.equals(phase);\n    }\n\n    static synchronized boolean reserveNewEntry(Context c, String symbol) {\n        if (symbol == null || symbol.trim().isEmpty()) return false;\n        String sym = symbol.trim().toUpperCase();\n        State existing = get(c, sym);\n        if (existing != null && !canReservePhase(existing.phase)) return false;\n\n        State pending = new State();\n        pending.symbol = sym;\n        pending.phase = ENTRY_PENDING;\n        pending.lastAction = "New Univest recommendation reserved before BUY dispatch.";\n        put(c, pending);\n        return true;\n    }\n\n    static synchronized void releasePendingEntry(Context c, String symbol, String reason) {\n        State state = get(c, symbol);\n        if (state == null || !ENTRY_PENDING.equals(state.phase)) return;\n        state.phase = EXITED;\n        state.quantity = 0;\n        state.principal = 0.0;\n        state.estimatedBuyCharges = 0.0;\n        state.lastAction = reason == null ? "Pending Univest entry released without an order." : reason;\n        put(c, state);\n    }\n\n'''
s = s.replace(insert_point, insert_point + reservation)
p.write_text(s)

# Replace raw-text 24-hour Univest dedupe with state/cycle-aware reservation.
p = j / 'MultyfiNotificationService.java'
s = p.read_text()
old = '''        String fingerprint = sha256("UNIVEST|" + signal.rawText);\n        if (!AppPrefs.claimFingerprint(getApplicationContext(), fingerprint)) {\n            AppPrefs.setUnivestStatus(getApplicationContext(), "Duplicate Univest " + signal.type + " ignored • " + signal.symbol + ".");\n            return;\n        }\n\n        final long postTime = sbn.getPostTime();\n        if (signal.type == UnivestParser.Type.ENTRY) {\n            if (!AppPrefs.isReadyForBuy(getApplicationContext())) {\n                AppPrefs.setUnivestStatus(getApplicationContext(), "UNIVEST ENTRY IGNORED • " + signal.symbol\n                        + " • Groww connection readiness is stale. Refresh/test authentication and static IP before enabling Univest.");\n                return;\n            }\n            int ub = AppPrefs.getUnivestBudget(getApplicationContext());\n            AppPrefs.setUnivestStatus(getApplicationContext(), "UNIVEST EQUITY ENTRY DETECTED • " + signal.symbol\n                    + " • saved budget ₹" + budgetText(ub) + " • CNC DELIVERY • fast path starting (one Groww LTP read only for quantity sizing).");\n            univestBuyExecutor.execute(() -> {\n                UnivestManager.handleEntry(getApplicationContext(), signal, postTime);\n                showLocalStatus("UNIVEST EQUITY", AppPrefs.getUnivestStatus(getApplicationContext()), true);\n            });\n        } else {\n            // EXIT has a dedicated executor so it cannot queue behind entry/monitor work.\n            AppPrefs.setUnivestStatus(getApplicationContext(), "UNIVEST OFFICIAL EXIT DETECTED • " + signal.symbol + " • priority CNC MARKET SELL path starting.");\n            univestExitExecutor.execute(() -> {\n                UnivestManager.handleExit(getApplicationContext(), signal, postTime);\n                showLocalStatus("UNIVEST EXIT", AppPrefs.getUnivestStatus(getApplicationContext()), true);\n            });\n        }\n'''
new = '''        final long postTime = sbn.getPostTime();\n        if (signal.type == UnivestParser.Type.ENTRY) {\n            if (!AppPrefs.isReadyForBuy(getApplicationContext())) {\n                AppPrefs.setUnivestStatus(getApplicationContext(), "UNIVEST ENTRY IGNORED • " + signal.symbol\n                        + " • Groww connection readiness is stale. Refresh/test authentication and static IP before enabling Univest.");\n                return;\n            }\n\n            // Recommendation-cycle dedupe: reserve the symbol synchronously before queuing the BUY.\n            // ACTIVE/PENDING recommendations reject repeats, but an officially EXITED symbol can start a new cycle\n            // immediately — even on the same day and even if Univest reuses identical notification text.\n            if (!UnivestStateStore.reserveNewEntry(getApplicationContext(), signal.symbol)) {\n                UnivestStateStore.State existing = UnivestStateStore.get(getApplicationContext(), signal.symbol);\n                String phase = existing == null ? "UNKNOWN" : existing.phase;\n                AppPrefs.setUnivestStatus(getApplicationContext(), "UNIVEST ENTRY DUPLICATE/ACTIVE IGNORED • " + signal.symbol\n                        + " • recommendation cycle already open in state " + phase + ".");\n                return;\n            }\n\n            int ub = AppPrefs.getUnivestBudget(getApplicationContext());\n            AppPrefs.setUnivestStatus(getApplicationContext(), "UNIVEST NEW RECOMMENDATION ACCEPTED • " + signal.symbol\n                    + " • saved budget ₹" + budgetText(ub) + " • CNC DELIVERY • fast path starting (one Groww LTP read only for quantity sizing).");\n            univestBuyExecutor.execute(() -> {\n                UnivestManager.handleEntry(getApplicationContext(), signal, postTime);\n                showLocalStatus("UNIVEST EQUITY", AppPrefs.getUnivestStatus(getApplicationContext()), true);\n            });\n        } else {\n            // Do not use a 24-hour raw-text fingerprint for Univest exits. The per-symbol state machine\n            // already rejects duplicate exits, while allowing a later same-day recommendation cycle to close normally.\n            AppPrefs.setUnivestStatus(getApplicationContext(), "UNIVEST OFFICIAL EXIT DETECTED • " + signal.symbol + " • priority CNC MARKET SELL path starting.");\n            univestExitExecutor.execute(() -> {\n                UnivestManager.handleExit(getApplicationContext(), signal, postTime);\n                showLocalStatus("UNIVEST EXIT", AppPrefs.getUnivestStatus(getApplicationContext()), true);\n            });\n        }\n'''
if old not in s:
    raise SystemExit('Univest fingerprint block not found')
s = s.replace(old, new)
p.write_text(s)

# Entry worker must execute only a synchronously reserved recommendation; release reservation on clean pre-order failures.
p = j / 'UnivestManager.java'
s = p.read_text()
old = '''        UnivestStateStore.State existing = UnivestStateStore.get(context, symbol);\n        if (existing != null && !UnivestStateStore.EXITED.equals(existing.phase)) {\n            status(context, "UNIVEST ENTRY IGNORED • " + symbol + " • recommendation already tracked in state " + existing.phase + ".");\n            return;\n        }\n'''
new = '''        UnivestStateStore.State existing = UnivestStateStore.get(context, symbol);\n        if (existing == null || !UnivestStateStore.canExecuteReservedPhase(existing.phase)) {\n            String phase = existing == null ? "NONE" : existing.phase;\n            status(context, "UNIVEST ENTRY IGNORED • " + symbol + " • no executable reservation; current state " + phase + ".");\n            return;\n        }\n'''
if old not in s:
    raise SystemExit('UnivestManager existing-state guard not found')
s = s.replace(old, new)

s = s.replace('''        if (instrument == null) {\n            status(context, "UNIVEST ENTRY SKIPPED • " + symbol + " • symbol not found in NSE CASH equity universe.");\n            return;\n        }\n''', '''        if (instrument == null) {\n            UnivestStateStore.releasePendingEntry(context, symbol, "Entry reservation released — symbol not found in NSE CASH equity universe.");\n            status(context, "UNIVEST ENTRY SKIPPED • " + symbol + " • symbol not found in NSE CASH equity universe.");\n            return;\n        }\n''')
s = s.replace('''        if (!instrument.buyAllowed) {\n            status(context, "UNIVEST ENTRY SKIPPED • " + symbol + " • Groww instrument master currently marks buy_allowed=0.");\n            return;\n        }\n''', '''        if (!instrument.buyAllowed) {\n            UnivestStateStore.releasePendingEntry(context, symbol, "Entry reservation released — Groww instrument master marks buy_allowed=0.");\n            status(context, "UNIVEST ENTRY SKIPPED • " + symbol + " • Groww instrument master currently marks buy_allowed=0.");\n            return;\n        }\n''')
s = s.replace('''        if (entryBudget <= 0) {\n            status(context, "UNIVEST ENTRY SKIPPED • " + symbol + " • saved Univest budget is ₹0.");\n            return;\n        }\n''', '''        if (entryBudget <= 0) {\n            UnivestStateStore.releasePendingEntry(context, symbol, "Entry reservation released — saved Univest budget is ₹0.");\n            status(context, "UNIVEST ENTRY SKIPPED • " + symbol + " • saved Univest budget is ₹0.");\n            return;\n        }\n''')
s = s.replace('''        if (!entry.submitted) {\n            status(context, "UNIVEST BUY NOT SUBMITTED • " + symbol + age(sourceAgeAtDispatch) + " • " + entry.message);\n            return;\n        }\n''', '''        if (!entry.submitted) {\n            UnivestStateStore.releasePendingEntry(context, symbol, "Entry reservation released — Groww BUY was not submitted. " + entry.message);\n            status(context, "UNIVEST BUY NOT SUBMITTED • " + symbol + age(sourceAgeAtDispatch) + " • " + entry.message);\n            return;\n        }\n''')
p.write_text(s)

# Add pure unit tests for the cycle policy.
p = root / 'app/src/test/java/com/suhas/multyfideliverybuy/UnivestStrategyContractTest.java'
s = p.read_text()
insert = '''\n    @org.junit.Test\n    public void officiallyExitedSymbolCanStartAnotherRecommendationCycleSameDay() {\n        org.junit.Assert.assertTrue(UnivestStateStore.canReservePhase(UnivestStateStore.EXITED));\n        org.junit.Assert.assertFalse(UnivestStateStore.canReservePhase(UnivestStateStore.ACTIVE));\n        org.junit.Assert.assertFalse(UnivestStateStore.canReservePhase(UnivestStateStore.ENTRY_PENDING));\n        org.junit.Assert.assertTrue(UnivestStateStore.canExecuteReservedPhase(UnivestStateStore.ENTRY_PENDING));\n        org.junit.Assert.assertFalse(UnivestStateStore.canExecuteReservedPhase(UnivestStateStore.EXITED));\n    }\n'''
idx = s.rfind('}')
if idx < 0:
    raise SystemExit('UnivestStrategyContractTest closing brace not found')
s = s[:idx] + insert + s[idx:]
p.write_text(s)

# UI / release wording.
p = j / 'MainActivity.java'
s = p.read_text()
s = s.replace('v1.4.1 • Delivery Trade Hub', 'v1.4.2 • Delivery Trade Hub')
s = s.replace('v1.4.1  •  DELIVERY FIRST', 'v1.4.2  •  DELIVERY FIRST')
s = s.replace('When enabled, only Univest equity/stock recommendations with Duration from 1 to 3 Months are eligible for entry. Every Univest order is NSE CASH / CNC DELIVERY — NEVER MIS / INTRADAY. Options, futures, commodities, durations over 3 months, shorter-than-1-month calls, and entries without a supported 1–3 month duration are ignored.',
              'When enabled, only Univest equity/stock recommendations with Duration from 1 to 3 Months are eligible for entry. Every Univest order is NSE CASH / CNC DELIVERY — NEVER MIS / INTRADAY. Duplicate notifications are blocked while a recommendation is active, but after an official Univest exit the same stock can be accepted again immediately as a new recommendation cycle. Options, futures, commodities, durations over 3 months, shorter-than-1-month calls, and entries without a supported 1–3 month duration are ignored.')
p.write_text(s)

# Static contract validation.
p = root / 'scripts/validate_contract.py'
s = p.read_text()
s = s.replace("'version 1.4.1':\"versionName '1.4.1'\" in gradle and 'versionCode 141' in gradle,",
              "'version 1.4.2':\"versionName '1.4.2'\" in gradle and 'versionCode 142' in gradle,")
marker = " 'Univest duration 1-3 months':'DURATION_MONTHS' in uparser and 'isEligibleEntryDuration' in uparser and 'end <= 3.0' in uparser and 'start >= 1.0' in uparser,\n"
extra = " 'Univest cycle-aware reentry':'ENTRY_PENDING' in ustate and 'reserveNewEntry' in ustate and 'canReservePhase' in ustate and 'canExecuteReservedPhase' in ustate and 'UNIVEST NEW RECOMMENDATION ACCEPTED' in service,\n 'Univest no raw 24h signal dedupe':'sha256(\"UNIVEST|\" + signal.rawText)' not in service,\n"
if marker not in s:
    raise SystemExit('validator duration marker not found')
s = s.replace(marker, marker + extra)
p.write_text(s)

# README release note.
p = root / 'README.md'
s = p.read_text()
s = s.replace('# Delivery Trade Hub — v1.4.1', '# Delivery Trade Hub — v1.4.2')
s += '''\n\n## v1.4.2 — Univest recommendation-cycle dedupe\n\n- Fixes same-stock same-day repeat recommendations after the earlier Univest recommendation has officially closed.\n- A new eligible 1–3 month Univest equity recommendation now reserves the symbol immediately before BUY dispatch.\n- Duplicate/repeated notifications are blocked while that recommendation is pending, active, averaging, re-entry waiting, or exiting.\n- Once the official Univest exit completes and the state is EXITED, the same stock may be accepted again immediately as a new recommendation cycle, even if Univest reuses identical notification wording on the same day.\n- Univest exits no longer use the generic 24-hour raw-notification fingerprint; the per-symbol state machine handles duplicate exits so a later recommendation cycle cannot have its legitimate exit suppressed.\n- All Univest entries remain CASH/CNC DELIVERY only, with the 1–3 month duration gate unchanged. All Multyfi/manual strategy behavior is unchanged.\n'''
p.write_text(s)

print('Applied Delivery Trade Hub v1.4.2 Univest recommendation-cycle dedupe fix')
