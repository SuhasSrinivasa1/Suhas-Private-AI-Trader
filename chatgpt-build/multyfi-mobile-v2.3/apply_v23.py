from pathlib import Path
import re
import shutil
import sys

app = Path(sys.argv[1]).resolve()
payload = Path(sys.argv[2]).resolve()

# Version + package lineage.
gradle = app / "app/build.gradle.kts"
s = gradle.read_text()
if 'versionCode = 220' not in s or 'versionName = "2.2.0"' not in s:
    raise SystemExit("V2.3 expected V2.2 version markers were not found")
s = s.replace('versionCode = 220', 'versionCode = 230', 1)
s = s.replace('versionName = "2.2.0"', 'versionName = "2.3.0"', 1)
gradle.write_text(s)

# Install the process/bootstrap Application class.
target = app / "app/src/main/java/com/intradayone/mobile/MultyfiApplication.kt"
target.parent.mkdir(parents=True, exist_ok=True)
shutil.copy2(payload / "MultyfiApplication.kt", target)

manifest = app / "app/src/main/AndroidManifest.xml"
s = manifest.read_text()
s, n = re.subn(r'android:label="[^"]*"', 'android:label="Multyfi Intraday Mobile V2.3"', s, count=1)
if n != 1:
    raise SystemExit("V2.3 could not update app label")
app_match = re.search(r'<application\b[^>]*>', s, flags=re.S)
if not app_match:
    raise SystemExit("V2.3 could not find <application> block")
application_tag = app_match.group(0)
if 'android:name=' not in application_tag:
    replacement = application_tag.replace('<application', '<application\n        android:name=".MultyfiApplication"', 1)
    s = s[:app_match.start()] + replacement + s[app_match.end():]
manifest.write_text(s)

# Critical V2.3 fix: candidate ingestion itself wakes/re-wakes the market scanner.
# This covers fresh notifications as well as active-notification replay after install.
repo = app / "app/src/main/java/com/intradayone/mobile/data/SessionRepository.kt"
s = repo.read_text()
needle = """    fun onMultyfi(context: Context, e: MultyfiEvent) {\n        rollDayIfNeeded(context)\n"""
if needle not in s:
    raise SystemExit("V2.3 could not locate SessionRepository.onMultyfi bootstrap point")
bootstrap = """    fun onMultyfi(context: Context, e: MultyfiEvent) {\n        rollDayIfNeeded(context)\n        // V2.3 market-data watchdog: every accepted/replayed Multyfi event re-wakes\n        // the foreground scanner. Starting an already-running service simply invokes\n        // onStartCommand again, which is intentional for stale/IDLE recovery.\n        try {\n            androidx.core.content.ContextCompat.startForegroundService(\n                context.applicationContext,\n                android.content.Intent(\n                    context.applicationContext,\n                    com.intradayone.mobile.service.MarketSessionService::class.java\n                )\n            )\n        } catch (t: Throwable) {\n            append(context, \"MARKET DATA START FAILED: ${t.javaClass.simpleName}: ${t.message ?: \"unknown\"}\")\n        }\n"""
s = s.replace(needle, bootstrap, 1)
repo.write_text(s)

# Mark new engine/runtime generation without invalidating V2.2 learning thresholds.
# The V2.3 change is scanner activation/recovery, not a new feature-space definition.
print("Applied V2.3 scanner bootstrap and market-data wake watchdog")
