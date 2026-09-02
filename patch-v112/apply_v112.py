from pathlib import Path

root = Path.cwd()
java_dir = root / 'app/src/main/java/com/suhas/multyfideliverybuy'

# Persisted Multyfi Intraday budget: 10k..100k in 10k steps, default 100k.
p = java_dir / 'AppPrefs.java'
s = p.read_text()
needle = '''    static boolean isMultibaggerEnabled(Context c) { return p(c).getBoolean("multibagger", false); }\n    static void setMultibaggerEnabled(Context c, boolean v) { p(c).edit().putBoolean("multibagger", v).apply(); }\n'''
replacement = '''    static boolean isMultibaggerEnabled(Context c) { return p(c).getBoolean("multibagger", false); }\n    static void setMultibaggerEnabled(Context c, boolean v) { p(c).edit().putBoolean("multibagger", v).apply(); }\n\n    static int getIntradayBudget(Context c) { return p(c).getInt("intraday_budget", 100000); }\n    static void setIntradayBudget(Context c, int v) {\n        int clamped = Math.max(10000, Math.min(100000, ((v + 9999) / 10000) * 10000));\n        p(c).edit().putInt("intraday_budget", clamped).apply();\n    }\n'''
if needle not in s:
    raise SystemExit('AppPrefs insertion point missing')
s = s.replace(needle, replacement)
p.write_text(s)

# UI: dedicated Intraday budget slider, independent of the existing manual LONG/SHORT slider.
p = java_dir / 'MainActivity.java'
s = p.read_text()
s = s.replace('''    private TextView lastOrderStatus;\n\n    private SeekBar manualBudgetBar;''', '''    private TextView lastOrderStatus;\n\n    private SeekBar intradayBudgetBar;\n    private TextView intradayBudgetValue;\n    private SeekBar manualBudgetBar;''')
s = s.replace('v1.1.0 MANUAL TRADE ADDITION', 'v1.1.2 INTRADAY BUDGET + NET GTT')
s = s.replace('''The original Multyfi notification engine remains unchanged. Manual LONG and SHORT are separate one-tap actions below. No stop-loss, trailing, re-entry or stock-price monitoring is added.''', '''Multyfi INTRADAY remains an immediate CNC MARKET BUY, now with a saved ₹10,000–₹1,00,000 daily budget. After actual fill confirmation the app immediately submits the broker-hosted net-1% CNC GTT target. Manual LONG and SHORT remain separate below.''')
old = '''        addCategoryCard(root, "INTRADAY", "₹1,00,000 fixed budget",\n                "Always enabled when master ARM is ON. Submitted as delivery CNC, not MIS.", null);\n'''
if old not in s:
    raise SystemExit('Intraday fixed card not found')
s = s.replace(old, '        addIntradayBudgetCard(root);\n')
marker = '''    private void addManualBudgetCard(LinearLayout root) {\n'''
method = '''    private void addIntradayBudgetCard(LinearLayout root) {\n        LinearLayout c = card(CARD);\n        c.addView(text("INTRADAY — MULTYFI DELIVERY", 18, TEXT, true));\n        c.addView(paddedText("Daily Multyfi budget • ₹10,000 to ₹1,00,000 • ₹10,000 steps", 13, MUTED, false, 0, 5, 0, 8));\n        intradayBudgetValue = text("₹1,00,000", 24, ACCENT, true);\n        c.addView(intradayBudgetValue);\n        intradayBudgetBar = new SeekBar(this);\n        intradayBudgetBar.setMax(9);\n        intradayBudgetBar.setProgress(9);\n        intradayBudgetBar.setPadding(0, dp(8), 0, dp(4));\n        c.addView(intradayBudgetBar, new LinearLayout.LayoutParams(-1, -2));\n        intradayBudgetBar.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {\n            public void onProgressChanged(SeekBar seekBar, int progress, boolean fromUser) {\n                intradayBudgetValue.setText("₹" + formatInr((progress + 1) * 10000));\n            }\n            public void onStartTrackingTouch(SeekBar seekBar) {}\n            public void onStopTrackingTouch(SeekBar seekBar) {}\n        });\n        Button saveBudget = button("SAVE INTRADAY BUDGET", BLUE);\n        c.addView(saveBudget, new LinearLayout.LayoutParams(-1, dp(50)));\n        saveBudget.setOnClickListener(v -> {\n            int budget = (intradayBudgetBar.getProgress() + 1) * 10000;\n            AppPrefs.setIntradayBudget(this, budget);\n            Toast.makeText(this, "Multyfi Intraday budget saved: ₹" + formatInr(budget), Toast.LENGTH_SHORT).show();\n        });\n        c.addView(paddedText(\n                "When armed, a valid Multyfi Intraday release uses this saved budget for quantity sizing, then submits the same immediate CNC MARKET BUY. The net-1% GTT is created only after the actual fill is confirmed.",\n                13, MUTED, false, 0, 8, 0, 0));\n        addCard(root, c);\n    }\n\n'''
if marker not in s:
    raise SystemExit('Manual budget method marker missing')
s = s.replace(marker, method + marker)
old = '''        armSwitch.setChecked(AppPrefs.isArmed(this));\n        int budget = AppPrefs.getManualBudget(this);\n        manualBudgetBar.setProgress(Math.max(0, Math.min(10, budget / 10000)));\n        manualBudgetValue.setText("₹" + formatInr(budget));\n'''
new = '''        armSwitch.setChecked(AppPrefs.isArmed(this));\n        int intradayBudget = AppPrefs.getIntradayBudget(this);\n        intradayBudgetBar.setProgress(Math.max(0, Math.min(9, (intradayBudget / 10000) - 1)));\n        intradayBudgetValue.setText("₹" + formatInr(intradayBudget));\n        int budget = AppPrefs.getManualBudget(this);\n        manualBudgetBar.setProgress(Math.max(0, Math.min(10, budget / 10000)));\n        manualBudgetValue.setText("₹" + formatInr(budget));\n'''
if old not in s:
    raise SystemExit('loadPrefs budget block missing')
s = s.replace(old, new)
s = s.replace('v1.1.0 • com.suhas.multyfideliverybuy', 'v1.1.2 • com.suhas.multyfideliverybuy')
s = s.replace('''Multyfi listener remains CNC BUY-only and ignores every later exit/closure notification. Manual LONG creates one CNC MARKET BUY and, after fill confirmation, one broker-hosted +1% GTT SELL target.''', '''Multyfi listener keeps the immediate CNC MARKET BUY entry and ignores later Multyfi exit/closure notifications. Intraday uses the saved ₹10k–₹1L budget and, after fill confirmation, creates one broker-hosted delivery GTT SELL target calculated for at least 1% estimated net profit. Manual LONG creates one CNC MARKET BUY and, after fill confirmation, one broker-hosted +1% GTT SELL target.''')
p.write_text(s)

# Notification engine: only budget sizing changes. CNC MARKET BUY and post-fill GTT logic remain unchanged.
p = java_dir / 'MultyfiNotificationService.java'
s = p.read_text()
old = '        final int budget = call.category == CallParser.Category.INTRADAY ? 100000 : 10000;\n'
new = '        final int budget = call.category == CallParser.Category.INTRADAY ? AppPrefs.getIntradayBudget(getApplicationContext()) : 10000;\n'
if old not in s:
    raise SystemExit('Fixed Intraday budget line missing')
s = s.replace(old, new)
s = s.replace('setStatus("Submitting " + call.category + " " + call.symbol + " • " + quantity + " shares • CNC MARKET BUY.");', 'setStatus("Submitting " + call.category + " " + call.symbol + " • budget ₹" + budgetText(budget) + " • " + quantity + " shares • CNC MARKET BUY.");')
s = s.replace('private static String budgetText(int v) { return v == 100000 ? "1,00,000" : "10,000"; }', '''private static String budgetText(int v) {\n        if (v >= 100000) return "1,00,000";\n        return String.format(Locale.US, "%d,000", v / 1000);\n    }''')
p.write_text(s)

# Version.
p = root / 'app/build.gradle'
s = p.read_text().replace('versionCode 111', 'versionCode 112').replace("versionName '1.1.1'", "versionName '1.1.2'")
p.write_text(s)

# Contract validation.
p = root / 'scripts/validate_contract.py'
s = p.read_text()
s = s.replace("'version 1.1.1': \"versionName '1.1.1'\" in gradle and 'versionCode 111' in gradle,", "'version 1.1.2': \"versionName '1.1.2'\" in gradle and 'versionCode 112' in gradle,")
s = s.replace("'Multyfi budget unchanged': '== CallParser.Category.INTRADAY ? 100000 : 10000' in service,", "'Multyfi intraday configurable budget': 'AppPrefs.getIntradayBudget' in service and 'intradayBudgetBar.setMax(9)' in main and '(progress + 1) * 10000' in main,")
needle = "    'manual default budget 50000': 'getInt(\"manual_budget\", 50000)' in (root / 'app/src/main/java/com/suhas/multyfideliverybuy/AppPrefs.java').read_text(),\n"
extra = "    'intraday default budget 100000': 'getInt(\"intraday_budget\", 100000)' in (root / 'app/src/main/java/com/suhas/multyfideliverybuy/AppPrefs.java').read_text(),\n    'intraday budget minimum 10000': 'Math.max(10000' in (root / 'app/src/main/java/com/suhas/multyfideliverybuy/AppPrefs.java').read_text(),\n"
if needle not in s:
    raise SystemExit('Validation insertion point missing')
s = s.replace(needle, needle + extra)
p.write_text(s)

p = root / 'README.md'
s = p.read_text().replace('# Multyfi Delivery Buy — v1.1.1', '# Multyfi Delivery Buy — v1.1.2')
s += '''\n\n## v1.1.2 — saved Multyfi Intraday budget\n\n- Dedicated Intraday slider: ₹10,000 to ₹1,00,000 in ₹10,000 steps, with explicit SAVE INTRADAY BUDGET.\n- Default remains ₹1,00,000 until changed.\n- Only Multyfi INTRADAY sizing uses this slider. Swing/Multibagger and manual LONG/SHORT budgets are unchanged.\n- The hot path still uses the Multyfi notification reference price for `floor(savedBudget/referencePrice)` and immediately submits the same NSE/CASH/CNC/MARKET/BUY; no pre-buy LTP request is added.\n- As soon as Groww order-detail confirms EXECUTED quantity and average price, the app immediately submits the broker-hosted CNC GTT SELL target calculated for at least 1.00% estimated net delivery profit. It does not wait for the Holdings UI or settlement display.\n- GTT triggering/execution is broker-side; there is still no stock-price watcher in the app.\n'''
p.write_text(s)

print('Applied Multyfi Delivery Buy v1.1.2 intraday budget slider patch')
