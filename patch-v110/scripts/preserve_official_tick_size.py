from pathlib import Path
p = Path('app/src/main/java/com/suhas/multyfideliverybuy/InstrumentRepository.java')
s = p.read_text()
old = '''    private static double normalizeTick(double v) {
        if (!(v > 0)) return 0.05;
        // Older Groww instrument snapshots have occasionally represented 5 paise as 5.
        if (v >= 1.0 && v <= 100.0 && Math.rint(v) == v) return v / 100.0;
        return v;
    }
'''
new = '''    private static double normalizeTick(double v) {
        if (!(v > 0)) return 0.05;
        // Groww's current official instrument master is authoritative for tick size.
        return v;
    }
'''
if old not in s:
    raise SystemExit('tick normalization block not found')
p.write_text(s.replace(old, new, 1))
