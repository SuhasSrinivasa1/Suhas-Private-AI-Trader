from pathlib import Path

root = Path.cwd()
j = root / 'app/src/main/java/com/suhas/multyfideliverybuy'

# Version bump.
p = root / 'app/build.gradle'
s = p.read_text()
s = s.replace('versionCode 140', 'versionCode 141')
s = s.replace("versionName '1.4.0'", "versionName '1.4.1'")
p.write_text(s)

# Univest ENTRY duration filter: only 1 to 3 months inclusive.
p = j / 'UnivestParser.java'
s = p.read_text()
needle = '    private static final Pattern STOCK = Pattern.compile("(?im)\\\\b(?:stock|symbol)\\\\s*[:\\\\-]\\\\s*([A-Z][A-Z0-9&\\\\-]{1,24})\\\\b");\n'
if needle not in s:
    raise SystemExit('STOCK pattern insertion point not found')
s = s.replace(needle, needle + '    private static final Pattern DURATION_MONTHS = Pattern.compile("(?im)\\\\bduration\\\\s*[:\\\\-]?\\\\s*(\\\\d+(?:\\\\.\\\\d+)?)\\\\s*(?:(?:-|–|—|to)\\\\s*(\\\\d+(?:\\\\.\\\\d+)?))?\\\\s*months?\\\\b");\n')

old = '''        boolean entry = containsAny(lower,\n                "new advisory pick", "new equity pick", "new stock pick", "equity pick", "stock recommendation");\n        if (entry) return new Signal(Type.ENTRY, symbol, text);\n\n        return null;\n    }\n\n    private static boolean containsAny(String text, String... values) {\n'''
new = '''        boolean entry = containsAny(lower,\n                "new advisory pick", "new equity pick", "new stock pick", "equity pick", "stock recommendation");\n        if (entry) {\n            if (!isEligibleEntryDuration(text)) return null;\n            return new Signal(Type.ENTRY, symbol, text);\n        }\n\n        return null;\n    }\n\n    private static boolean isEligibleEntryDuration(String text) {\n        Matcher duration = DURATION_MONTHS.matcher(text);\n        if (!duration.find()) return false;\n        try {\n            double start = Double.parseDouble(duration.group(1));\n            double end = duration.group(2) == null ? start : Double.parseDouble(duration.group(2));\n            return start >= 1.0 && end >= start && end <= 3.0;\n        } catch (NumberFormatException e) {\n            return false;\n        }\n    }\n\n    private static boolean containsAny(String text, String... values) {\n'''
if old not in s:
    raise SystemExit('ENTRY block not found')
s = s.replace(old, new)
p.write_text(s)

# Add explicit unit tests for the duration gate and ensure exits are not blocked by duration.
p = root / 'app/src/test/java/com/suhas/multyfideliverybuy/UnivestParserTest.java'
s = p.read_text()
insert = '''\n    @org.junit.Test\n    public void entryAcceptsOneToThreeMonthRange() {\n        UnivestParser.Signal s = UnivestParser.parse("New Advisory Pick\\nSTOCK: PANAMAPET\\nDuration: 1-3 Months\\nPotential: 5.38%");\n        org.junit.Assert.assertNotNull(s);\n        org.junit.Assert.assertEquals(UnivestParser.Type.ENTRY, s.type);\n        org.junit.Assert.assertEquals("PANAMAPET", s.symbol);\n    }\n\n    @org.junit.Test\n    public void entryAcceptsSingleThreeMonthDuration() {\n        UnivestParser.Signal s = UnivestParser.parse("New Advisory Pick\\nSTOCK: AEGISLOG\\nDuration: 3 Months");\n        org.junit.Assert.assertNotNull(s);\n        org.junit.Assert.assertEquals(UnivestParser.Type.ENTRY, s.type);\n    }\n\n    @org.junit.Test\n    public void entryRejectsDurationOverThreeMonths() {\n        org.junit.Assert.assertNull(UnivestParser.parse("New Advisory Pick\\nSTOCK: ABC\\nDuration: 6 Months"));\n        org.junit.Assert.assertNull(UnivestParser.parse("New Advisory Pick\\nSTOCK: ABC\\nDuration: 3-6 Months"));\n    }\n\n    @org.junit.Test\n    public void entryRejectsMissingOrSubMonthDuration() {\n        org.junit.Assert.assertNull(UnivestParser.parse("New Advisory Pick\\nSTOCK: ABC"));\n        org.junit.Assert.assertNull(UnivestParser.parse("New Advisory Pick\\nSTOCK: ABC\\nDuration: 2 Weeks"));\n    }\n\n    @org.junit.Test\n    public void exitIsNotBlockedByDurationGate() {\n        UnivestParser.Signal s = UnivestParser.parse("5th Equity Profit of the Day\\nStock: GVPIL\\nDuration: 2 Days");\n        org.junit.Assert.assertNotNull(s);\n        org.junit.Assert.assertEquals(UnivestParser.Type.EXIT, s.type);\n        org.junit.Assert.assertEquals("GVPIL", s.symbol);\n    }\n'''
idx = s.rfind('}')
if idx < 0:
    raise SystemExit('UnivestParserTest closing brace not found')
s = s[:idx] + insert + s[idx:]
p.write_text(s)

# Update visible Univest wording.
p = j / 'MainActivity.java'
s = p.read_text()
s = s.replace('When enabled, only Univest equity/stock recommendations are automated. Every Univest order is NSE CASH / CNC DELIVERY — NEVER MIS / INTRADAY. Options, futures, commodities and all non-equity calls are ignored.',
              'When enabled, only Univest equity/stock recommendations with Duration from 1 to 3 Months are eligible for entry. Every Univest order is NSE CASH / CNC DELIVERY — NEVER MIS / INTRADAY. Options, futures, commodities, durations over 3 months, shorter-than-1-month calls, and entries without a supported 1–3 month duration are ignored.')
s = s.replace('UNIVEST: equity calls are always CNC DELIVERY, with your saved ₹0–₹1,00,000 entry budget. Averaging remains fixed at ₹5,000 at −3% / −6% / −9%; profit capture is ₹2,500 NET.',
              'UNIVEST: only equity entries with Duration 1–3 Months are eligible. Orders are always CNC DELIVERY, with your saved ₹0–₹1,00,000 entry budget. Averaging remains fixed at ₹5,000 at −3% / −6% / −9%; profit capture is ₹2,500 NET.')
s = s.replace('• Univest equity: CNC DELIVERY only; saved entry budget; ₹5,000 averaging at −3% / −6% / −9%; ₹2,500 estimated NET-profit capture.',
              '• Univest equity: ENTRY only when Duration is 1–3 Months; CNC DELIVERY only; saved entry budget; ₹5,000 averaging at −3% / −6% / −9%; ₹2,500 estimated NET-profit capture.')
s = s.replace('v1.4.0 • Delivery Trade Hub', 'v1.4.1 • Delivery Trade Hub')
s = s.replace('v1.4.0  •  DELIVERY FIRST', 'v1.4.1  •  DELIVERY FIRST')
p.write_text(s)

# Extend static contract validator.
p = root / 'scripts/validate_contract.py'
s = p.read_text()
s = s.replace("'version 1.4.0':\"versionName '1.4.0'\" in gradle and 'versionCode 140' in gradle,",
              "'version 1.4.1':\"versionName '1.4.1'\" in gradle and 'versionCode 141' in gradle,")
marker = " 'Univest equity only filters':"
idx = s.find(marker)
if idx < 0:
    raise SystemExit('validator Univest marker not found')
line_end = s.find('\n', idx)
extra = "\n 'Univest duration 1-3 months':'DURATION_MONTHS' in univest_parser and 'isEligibleEntryDuration' in univest_parser and 'end <= 3.0' in univest_parser and 'start >= 1.0' in univest_parser,"
s = s[:line_end] + extra + s[line_end:]
p.write_text(s)

# README note.
p = root / 'README.md'
s = p.read_text()
s = s.replace('# Delivery Trade Hub — v1.4.0', '# Delivery Trade Hub — v1.4.1')
s += '''\n\n## v1.4.1 — Univest duration gate\n\n- Univest new equity ENTRY is eligible only when the notification explicitly carries a duration from 1 to 3 months inclusive.\n- Examples accepted: 1 Month, 2 Months, 3 Months, 1-2 Months, 1-3 Months.\n- Durations above 3 months, below 1 month, non-month durations, and new entries with no supported duration are ignored.\n- This duration gate applies only to new Univest entries. Existing-position Univest Profit Booked / Close / Exit notifications remain actionable regardless of duration text.\n- All other v1.4.0 strategy rules are unchanged.\n'''
p.write_text(s)

print('Applied Delivery Trade Hub v1.4.1 Univest duration filter')
