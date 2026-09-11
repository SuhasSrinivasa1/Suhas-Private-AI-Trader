from pathlib import Path

root = Path.cwd()
j = root / 'app/src/main/java/com/suhas/multyfideliverybuy'

# Version bump.
p = root / 'app/build.gradle'
s = p.read_text()
s = s.replace('versionCode 145', 'versionCode 146')
s = s.replace("versionName '1.4.5'", "versionName '1.4.6'")
p.write_text(s)

# Univest notifications may carry an NSE series suffix such as HFCL-BE.
# Groww order APIs use the exchange trading_symbol itself (HFCL here), while series
# is a separate instrument-master field. Normalize only the explicit -BE suffix.
p = j / 'UnivestParser.java'
s = p.read_text()
needle = '''        String symbol = m.group(1).trim();\n        if (symbol.isEmpty()) return null;\n'''
replacement = '''        String symbol = m.group(1).trim();\n        if (symbol.isEmpty()) return null;\n        // Univest sometimes appends the NSE series to the displayed symbol (e.g. HFCL-BE).\n        // Groww expects the exchange trading_symbol, with series validated separately.\n        if (symbol.endsWith("-BE") && symbol.length() > 3) {\n            symbol = symbol.substring(0, symbol.length() - 3);\n        }\n'''
if needle not in s:
    raise SystemExit('Expected Univest symbol parse block not found')
s = s.replace(needle, replacement)
p.write_text(s)

# Keep the NSE CASH equity universe strict, but accept both ordinary EQ and BE
# (trade-for-trade) equity series from Groww's official instrument master.
p = j / 'InstrumentRepository.java'
s = p.read_text()
old = '                if (!series.isEmpty() && !"EQ".equalsIgnoreCase(series)) continue;\n'
new = '                if (!series.isEmpty() && !"EQ".equalsIgnoreCase(series) && !"BE".equalsIgnoreCase(series)) continue;\n'
if old not in s:
    raise SystemExit('Expected EQ-only series filter not found')
s = s.replace(old, new)
p.write_text(s)

# UI version only. Fast BUY/SELL execution paths are untouched.
p = j / 'MainActivity.java'
s = p.read_text()
s = s.replace('v1.4.5  •  DELIVERY FIRST', 'v1.4.6  •  DELIVERY FIRST')
s = s.replace('v1.4.5 • Delivery Trade Hub', 'v1.4.6 • Delivery Trade Hub')
p.write_text(s)

# Unit coverage for the exact production symptom: HFCL-BE must resolve to the
# broker trading symbol HFCL for both ENTRY and EXIT notifications.
p = root / 'app/src/test/java/com/suhas/multyfideliverybuy/UnivestParserTest.java'
s = p.read_text()
insert = '''\n    @org.junit.Test\n    public void normalizesBeSeriesSuffixForEntryAndExit() {\n        UnivestParser.Signal entry = UnivestParser.parse("New Advisory Pick\\nSTOCK: HFCL-BE\\nDuration: 1-3 Months");\n        org.junit.Assert.assertNotNull(entry);\n        org.junit.Assert.assertEquals(UnivestParser.Type.ENTRY, entry.type);\n        org.junit.Assert.assertEquals("HFCL", entry.symbol);\n\n        UnivestParser.Signal exit = UnivestParser.parse("Equity Profit Booked\\nStock: HFCL-BE\\nDuration: 2 Days");\n        org.junit.Assert.assertNotNull(exit);\n        org.junit.Assert.assertEquals(UnivestParser.Type.EXIT, exit.type);\n        org.junit.Assert.assertEquals("HFCL", exit.symbol);\n    }\n'''
pos = s.rfind('}')
if pos < 0:
    raise SystemExit('UnivestParserTest closing brace not found')
s = s[:pos] + insert + s[pos:]
p.write_text(s)

# Static contract validator.
p = root / 'scripts/validate_contract.py'
s = p.read_text()
s = s.replace("'version 1.4.5':\"versionName '1.4.5'\" in gradle and 'versionCode 145' in gradle,",
              "'version 1.4.6':\"versionName '1.4.6'\" in gradle and 'versionCode 146' in gradle,")
marker = "'Univest equity only filters'"
if marker not in s:
    raise SystemExit('Expected validator Univest equity filter marker not found')
# Add explicit checks without weakening any existing equity/F&O filter checks.
checks = "        'Univest BE series supported':'symbol.endsWith(\\\"-BE\\\")' in uparser and '!\\\"BE\\\".equalsIgnoreCase(series)' in instruments,\n"
# Determine variable used for InstrumentRepository text.
if "instruments =" not in s:
    # Older validator uses repository variable name 'instrument'.
    if "instrument =" in s:
        checks = checks.replace("in instruments", "in instrument")
    else:
        raise SystemExit('Could not locate instrument repository validator variable')
# Insert before equity-only check to make failure obvious.
idx = s.find("        'Univest equity only filters'")
s = s[:idx] + checks + s[idx:]
p.write_text(s)

# Release notes.
p = root / 'README.md'
s = p.read_text()
s += '''\n\n## v1.4.6 — Univest BE-series symbol fix\n\n- Fixes Univest recommendations displayed with an NSE `-BE` suffix, such as `HFCL-BE`.\n- `HFCL-BE` is normalized to Groww/NSE trading symbol `HFCL` before reservation and order execution, so fast BUY and later EXIT use the same canonical state key.\n- Groww official instrument-master filtering now permits both `EQ` and `BE` NSE CASH equity series while still rejecting F&O, options, futures, commodities and reserved/non-tradable instruments.\n- Fast Univest BUY, dedicated fast EXIT, four averaging adds at −2/−4/−6/−8%, ₹2,500 net-profit capture, and the −20% protective broker GTT are unchanged.\n- LG G7 ThinQ compatibility remains unchanged (minSdk 26; no native ABI dependency added).\n'''
p.write_text(s)

print('Applied Delivery Trade Hub v1.4.6 Univest BE-series symbol fix')
