from pathlib import Path

p = Path.cwd() / 'app/src/main/java/com/suhas/multyfideliverybuy/MainActivity.java'
s = p.read_text()

bad1 = '''                "UNIVEST: equity calls are always CNC DELIVERY, with your saved ₹0–₹1,00,000 entry budget. Averaging remains fixed at ₹5,000 at −3% / −6% / −9%; profit capture is ₹2,500 NET.

MULTYFI EQUITY: entry is always CNC DELIVERY even when the source notification says Intraday. Primary exit is +0.5% estimated NET profit, with the first-spike fallback. A confirmed Multyfi close/end signal may start the separate MIS short strategy with +0.5% estimated NET target and a 1% budget-loss stop guard.",'''
good1 = r'''                "UNIVEST: equity calls are always CNC DELIVERY, with your saved ₹0–₹1,00,000 entry budget. Averaging remains fixed at ₹5,000 at −3% / −6% / −9%; profit capture is ₹2,500 NET.\n\nMULTYFI EQUITY: entry is always CNC DELIVERY even when the source notification says Intraday. Primary exit is +0.5% estimated NET profit, with the first-spike fallback. A confirmed Multyfi close/end signal may start the separate MIS short strategy with +0.5% estimated NET target and a 1% budget-loss stop guard.",'''
if bad1 not in s:
    raise SystemExit('overview raw-newline string not found')
s = s.replace(bad1, good1)

bad2 = '''                "• Univest equity: CNC DELIVERY only; saved entry budget; ₹5,000 averaging at −3% / −6% / −9%; ₹2,500 estimated NET-profit capture.

• Multyfi equity entry: CNC DELIVERY only; saved budget; +0.5% estimated NET-profit GTT target with first-spike fallback.

• Multyfi authoritative close/end: tracked delivery exit is reconciled first, then the separate MIS short may open with +0.5% estimated NET target and a 1% budget-loss stop guard.

• Manual LONG remains CNC delivery. Manual SHORT remains MIS intraday.",'''
good2 = r'''                "• Univest equity: CNC DELIVERY only; saved entry budget; ₹5,000 averaging at −3% / −6% / −9%; ₹2,500 estimated NET-profit capture.\n\n• Multyfi equity entry: CNC DELIVERY only; saved budget; +0.5% estimated NET-profit GTT target with first-spike fallback.\n\n• Multyfi authoritative close/end: tracked delivery exit is reconciled first, then the separate MIS short may open with +0.5% estimated NET target and a 1% budget-loss stop guard.\n\n• Manual LONG remains CNC delivery. Manual SHORT remains MIS intraday.",'''
if bad2 not in s:
    raise SystemExit('contract raw-newline string not found')
s = s.replace(bad2, good2)

p.write_text(s)
print('Fixed Java UI string escaping for v1.4.0')
