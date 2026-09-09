from pathlib import Path

root = Path.cwd()
j = root / 'app/src/main/java/com/suhas/multyfideliverybuy'

# Version bump.
p = root / 'app/build.gradle'
s = p.read_text()
s = s.replace('versionCode 130', 'versionCode 140')
s = s.replace("versionName '1.3.0'", "versionName '1.4.0'")
p.write_text(s)

# App label: broader name now that Univest + Multyfi + manual trading share one app.
p = root / 'app/src/main/AndroidManifest.xml'
s = p.read_text()
s = s.replace('android:label="Multyfi Delivery Buy"', 'android:label="Delivery Trade Hub"')
s = s.replace('android:label="Multyfi Delivery Buy listener"', 'android:label="Delivery Trade Hub listener"')
p.write_text(s)

# UI polish + remove stale v1.3 wording.
p = j / 'MainActivity.java'
s = p.read_text()
s = s.replace('private static final int BG = Color.rgb(7, 10, 15);', 'private static final int BG = Color.rgb(5, 9, 14);')
s = s.replace('private static final int CARD = Color.rgb(15, 22, 31);', 'private static final int CARD = Color.rgb(13, 21, 30);')
s = s.replace('private static final int CARD_2 = Color.rgb(20, 30, 41);', 'private static final int CARD_2 = Color.rgb(18, 30, 42);')
s = s.replace('private static final int BLUE = Color.rgb(76, 111, 255);', 'private static final int BLUE = Color.rgb(88, 122, 255);')

s = s.replace('root.addView(text("Multyfi Delivery Buy", 28, TEXT, true));', 'root.addView(text("Delivery Trade Hub", 30, TEXT, true));')
s = s.replace('TextView sub = text("Multyfi + Univest equity delivery automation + manual LONG / SHORT", 14, ACCENT, true);',
'''TextView sub = text("MULTYFI  •  UNIVEST  •  MANUAL  •  GROWW API", 13, ACCENT, true);''')

old = '''        LinearLayout warning = card(CARD_2);\n        warning.addView(text("v1.3.0 UNIVEST + MULTYFI EXIT UPDATE", 13, WARN, true));\n        warning.addView(paddedText(\n                "Univest remains EQUITY DELIVERY ONLY, now with a saved ₹0–₹1,00,000 entry budget. Averaging stays fixed at ₹5,000 at −3% / −6% / −9% and ₹2,500 NET profit capture remains unchanged. Multyfi Intraday entries remain CNC DELIVERY, with a +0.5% NET-on-budget target and first-spike fallback; an authoritative Multyfi close signal starts a separate MIS short with +0.5% NET target and a 1% budget-loss stop guard.",\n                14, TEXT, false, 0, 8, 0, 0));\n        addCard(root, warning);\n'''
new = '''        LinearLayout warning = card(CARD_2);\n        warning.addView(text("v1.4.0  •  DELIVERY FIRST", 13, WARN, true));\n        warning.addView(paddedText(\n                "UNIVEST: equity calls are always CNC DELIVERY, with your saved ₹0–₹1,00,000 entry budget. Averaging remains fixed at ₹5,000 at −3% / −6% / −9%; profit capture is ₹2,500 NET.\n\nMULTYFI EQUITY: entry is always CNC DELIVERY even when the source notification says Intraday. Primary exit is +0.5% estimated NET profit, with the first-spike fallback. A confirmed Multyfi close/end signal may start the separate MIS short strategy with +0.5% estimated NET target and a 1% budget-loss stop guard.",\n                14, TEXT, false, 0, 8, 0, 0));\n        addCard(root, warning);\n'''
if old not in s:
    raise SystemExit('v1.3 overview card not found')
s = s.replace(old, new)

s = s.replace('master.addView(text("Multyfi instant delivery BUY", 19, TEXT, true));', 'master.addView(text("MULTYFI • AUTOMATION", 19, TEXT, true));')
s = s.replace('''                "When armed, a newly released eligible Multyfi call is sent directly as Groww CASH / CNC / MARKET / BUY. ARM is allowed only after today's static-IP and Groww authentication test passes.",''',
'''                "When armed, a new eligible Multyfi equity call is sent immediately as Groww CASH / CNC / MARKET / BUY — DELIVERY. This remains delivery even if Multyfi calls it Intraday. ARM is allowed only after today's static-IP and Groww authentication test passes.",''')
s = s.replace('armSwitch = switchView("ARM Multyfi BUY listener");', 'armSwitch = switchView("ARM Multyfi automation");')

s = s.replace('univest.addView(text("UNIVEST — EQUITY DELIVERY ONLY", 19, TEXT, true));', 'univest.addView(text("UNIVEST • EQUITY DELIVERY ONLY", 19, TEXT, true));')
s = s.replace('''                "When enabled, only Univest equity/stock recommendations are automated. Every Univest order is NSE CASH / CNC DELIVERY — never MIS. Options, futures, commodities and other non-equity calls are ignored.",''',
'''                "When enabled, only Univest equity/stock recommendations are automated. Every Univest order is NSE CASH / CNC DELIVERY — NEVER MIS / INTRADAY. Options, futures, commodities and all non-equity calls are ignored.",''')

s = s.replace('status.addView(text("Readiness status", 19, TEXT, true));', 'status.addView(text("SYSTEM READINESS", 19, TEXT, true));')

old_contract = '''        LinearLayout contract = card(Color.rgb(11, 26, 24));\n        contract.addView(text("LOCKED EXECUTION CONTRACT", 13, ACCENT, true));\n        contract.addView(paddedText(\n                "Multyfi listener keeps the immediate CNC MARKET BUY entry and ignores later Multyfi exit/closure notifications. Intraday uses the saved ₹10k–₹1L budget and, after fill confirmation, creates one broker-hosted delivery GTT SELL target calculated for at least 1% estimated net profit. Manual LONG creates one CNC MARKET BUY and, after fill confirmation, one broker-hosted +1% GTT SELL target. Manual SHORT creates one MIS MARKET SELL and one broker-hosted -1% GTT BUY-to-cover target. No stop-loss, trailing, re-entry, P&L engine, candle analysis or ongoing stock-price monitoring.",\n                14, TEXT, false, 0, 8, 0, 0));\n        addCard(root, contract);\n\n        TextView foot = text("v1.3.0 • com.suhas.multyfideliverybuy", 12, MUTED, false);\n'''
new_contract = '''        LinearLayout contract = card(Color.rgb(10, 28, 25));\n        contract.addView(text("EXECUTION CONTRACT", 13, ACCENT, true));\n        contract.addView(paddedText(\n                "• Univest equity: CNC DELIVERY only; saved entry budget; ₹5,000 averaging at −3% / −6% / −9%; ₹2,500 estimated NET-profit capture.\n\n• Multyfi equity entry: CNC DELIVERY only; saved budget; +0.5% estimated NET-profit GTT target with first-spike fallback.\n\n• Multyfi authoritative close/end: tracked delivery exit is reconciled first, then the separate MIS short may open with +0.5% estimated NET target and a 1% budget-loss stop guard.\n\n• Manual LONG remains CNC delivery. Manual SHORT remains MIS intraday.",\n                14, TEXT, false, 0, 8, 0, 0));\n        addCard(root, contract);\n\n        TextView foot = text("v1.4.0 • Delivery Trade Hub", 12, MUTED, false);\n'''
if old_contract not in s:
    raise SystemExit('stale execution contract block not found')
s = s.replace(old_contract, new_contract)

s = s.replace('c.addView(text("INTRADAY — MULTYFI DELIVERY", 18, TEXT, true));', 'c.addView(text("MULTYFI EQUITY • DELIVERY BUDGET", 18, TEXT, true));')
s = s.replace('''c.addView(paddedText("Daily Multyfi budget • ₹10,000 to ₹1,00,000 • ₹10,000 steps", 13, MUTED, false, 0, 5, 0, 8));''',
'''c.addView(paddedText("₹10,000 to ₹1,00,000 • ₹10,000 steps • applies to Multyfi equity entry and close-triggered short sizing", 13, MUTED, false, 0, 5, 0, 8));''')
s = s.replace('''                "When armed, a valid Multyfi Intraday release uses this saved budget for the same immediate CNC DELIVERY MARKET BUY. After fill, the primary exit target is +0.5% NET profit on the saved entry budget. A first-spike fallback may lower the GTT after a confirmed sharp pullback. Multyfi close/end signals are handled separately as MIS shorts.",''',
'''                "A valid Multyfi equity release uses this saved budget for the immediate CNC DELIVERY MARKET BUY. After fill, the primary target is +0.5% estimated NET profit on the entry budget. The first-spike fallback can lower that GTT only after its pullback rule confirms. Multyfi close/end is handled separately as an MIS short strategy.",''')

p.write_text(s)

# Contract validator v1.4 + UI assertions.
p = root / 'scripts/validate_contract.py'
s = p.read_text()
s = s.replace("'version 1.3.0':\"versionName '1.3.0'\" in gradle and 'versionCode 130' in gradle,",
              "'version 1.4.0':\"versionName '1.4.0'\" in gradle and 'versionCode 140' in gradle,")
marker = " 'Univest toggle':'Enable Univest equity automation' in main and 'isUnivestEnabled' in prefs,\n"
extra = " 'UI delivery wording':'Delivery Trade Hub' in main and 'NEVER MIS / INTRADAY' in main and '+0.5% estimated NET-profit GTT target' in main,\n"
if marker not in s:
    raise SystemExit('validator insertion point missing')
s = s.replace(marker, marker + extra)
p.write_text(s)

# README release note.
p = root / 'README.md'
s = p.read_text()
s = s.replace('# Multyfi Delivery Buy — v1.1.1', '# Delivery Trade Hub — v1.4.0')
s += '''\n\n## v1.4.0 — fresh signed UI release\n\n- Refreshed dark control-center UI and clearer strategy wording.\n- Univest is always NSE CASH/CNC DELIVERY and never MIS, with saved ₹0–₹1,00,000 entry budget.\n- Univest averaging remains fixed at ₹5,000 at −3%, −6%, −9% from original executed entry; ₹2,500 estimated NET profit capture retained.\n- Multyfi equity entries remain CNC DELIVERY even when source labels the call Intraday.\n- Multyfi equity primary target is +0.5% estimated NET profit on entry budget, with deterministic first-spike fallback retained.\n- Authoritative Multyfi close/end may start the separate MIS short after delivery reconciliation, with +0.5% estimated NET target and 1% budget-loss stop guard.\n- Fresh signing identity is generated for this release because the previous installation was intentionally removed. Keep the signing backup for future in-place upgrades.\n'''
p.write_text(s)

print('Applied Delivery Trade Hub v1.4.0 UI/version patch')
