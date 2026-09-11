from pathlib import Path

root = Path.cwd()
j = root / 'app/src/main/java/com/suhas/multyfideliverybuy'

# Version bump.
p = root / 'app/build.gradle'
s = p.read_text()
s = s.replace('versionCode 144', 'versionCode 145')
s = s.replace("versionName '1.4.4'", "versionName '1.4.5'")
p.write_text(s)

# Univest protective stop: move from -10% to -20%, keep original-entry anchor and full-quantity resize behavior.
p = j / 'UnivestManager.java'
s = p.read_text()
if 'static final double PROTECTIVE_STOP_DROP = 0.10;' not in s:
    raise SystemExit('Expected v1.4.4 protective stop constant not found')
s = s.replace('static final double PROTECTIVE_STOP_DROP = 0.10;', 'static final double PROTECTIVE_STOP_DROP = 0.20;')
s = s.replace('−10%', '−20%')
p.write_text(s)

# UI/release wording only; fast-buy and fast-sell paths are unchanged.
p = j / 'MainActivity.java'
s = p.read_text()
s = s.replace('v1.4.4  •  DELIVERY FIRST', 'v1.4.5  •  DELIVERY FIRST')
s = s.replace('v1.4.4 • Delivery Trade Hub', 'v1.4.5 • Delivery Trade Hub')
s = s.replace('−10% protective', '−20% protective')
s = s.replace('−10% CNC SELL GTT', '−20% CNC SELL GTT')
s = s.replace('−10% protective GTT', '−20% protective GTT')
p.write_text(s)

# Unit test expectation for the new stop distance.
p = root / 'app/src/test/java/com/suhas/multyfideliverybuy/UnivestStrategyContractTest.java'
s = p.read_text()
s = s.replace('public void protectiveStopIsTenPercentBelowOriginalEntry()', 'public void protectiveStopIsTwentyPercentBelowOriginalEntry()')
s = s.replace('org.junit.Assert.assertEquals(0.10, UnivestManager.PROTECTIVE_STOP_DROP, 0.000001);',
              'org.junit.Assert.assertEquals(0.20, UnivestManager.PROTECTIVE_STOP_DROP, 0.000001);')
s = s.replace('org.junit.Assert.assertEquals(90.0, UnivestManager.protectiveStopPrice(100.0, 0.05), 0.0001);',
              'org.junit.Assert.assertEquals(80.0, UnivestManager.protectiveStopPrice(100.0, 0.05), 0.0001);')
s = s.replace('org.junit.Assert.assertEquals(111.15, UnivestManager.protectiveStopPrice(123.47, 0.05), 0.0001);',
              'org.junit.Assert.assertEquals(98.8, UnivestManager.protectiveStopPrice(123.47, 0.05), 0.0001);')
p.write_text(s)

# Static contract validator.
p = root / 'scripts/validate_contract.py'
s = p.read_text()
s = s.replace("'version 1.4.4':\"versionName '1.4.4'\" in gradle and 'versionCode 144' in gradle,",
              "'version 1.4.5':\"versionName '1.4.5'\" in gradle and 'versionCode 145' in gradle,")
s = s.replace("'Univest protective stop 10 percent':'PROTECTIVE_STOP_DROP = 0.10' in univest and 'createUnivestCncStopGtt' in groww and 'modifyUnivestCncStopGtt' in groww and 'protectiveStopGttId' in ustate and '\"MARKET\"' in groww,",
              "'Univest protective stop 20 percent':'PROTECTIVE_STOP_DROP = 0.20' in univest and 'createUnivestCncStopGtt' in groww and 'modifyUnivestCncStopGtt' in groww and 'protectiveStopGttId' in ustate and '\"MARKET\"' in groww,")
p.write_text(s)

# README / release note.
p = root / 'README.md'
s = p.read_text()
s = s.replace('armed at −10% from the original executed entry', 'armed at −20% from the original executed entry')
s += '''\n\n## v1.4.5 — Univest −20% broker protection\n\n- Protective broker-hosted Univest CNC SELL GTT moves from −10% to −20% from the original first executed entry price.\n- The stop remains anchored to the original first fill and never moves lower after averaging.\n- Protective GTT quantity is still resized to cover the full tracked Univest quantity after each confirmed average/re-entry fill.\n- Downward averaging remains unchanged: four maximum ₹5,000 adds at −2%, −4%, −6% and −8% from the original first fill.\n- Univest fast BUY and dedicated fast EXIT paths are unchanged.\n- LG G7 ThinQ compatibility remains unchanged (minSdk 26; no native ABI dependency added).\n- The −20% value is a trigger level, not a guaranteed realized-loss cap; a market order may fill lower during a gap/fast move.\n'''
p.write_text(s)

print('Applied Delivery Trade Hub v1.4.5 Univest -20% protective stop')
