from pathlib import Path
import runpy

"""
Multyfi Intraday Mobile V3.0.10 source transformation entry point.

Purpose
-------
Transforms the verified V3.0.8 Android source tree into V3.0.10 by applying:
  1) V3.0.9 feed-resilience protections.
  2) V3.0.10 market-integrity and anti-churn protections.

Expected baseline
-----------------
Multyfi_Intraday_Mobile_V3_0 must already be at versionCode 308 / versionName 3.0.8.

Result
------
versionCode 310 / versionName 3.0.10, minSdk 26.
Live Buy & Sell remains OFF by default.
"""

ROOT = Path(__file__).resolve().parent
APP = ROOT / "Multyfi_Intraday_Mobile_V3_0"
GRADLE = APP / "app" / "build.gradle.kts"
V309 = ROOT / ".github" / "build-scripts" / "apply-v309-feed-resilience.py"
V310 = ROOT / ".github" / "build-scripts" / "apply-v310-market-integrity.py"

for required in (GRADLE, V309, V310):
    if not required.exists():
        raise SystemExit(f"Required source file missing: {required}")

before = GRADLE.read_text()
if "versionCode = 308" not in before or 'versionName = "3.0.8"' not in before:
    raise SystemExit("Expected verified V3.0.8 source baseline before applying V3.0.10")

# Feed resilience: DNS/timeout/API/rate-limit classification, degraded-feed gating,
# controlled retry/backoff and clean-feed recovery warm-up.
runpy.run_path(str(V309), run_name="__main__")

mid = GRADLE.read_text()
if "versionCode = 309" not in mid or 'versionName = "3.0.9"' not in mid:
    raise SystemExit("V3.0.9 feed-resilience source transformation did not complete")

# Market integrity + anti-churn: exchange timestamps, stale/duplicate/out-of-order
# filtering, cumulative-volume regression rejection, replay sanitation, 3-tick
# confirmation, 90-second re-entry cooldown and no immediate flip re-entry.
runpy.run_path(str(V310), run_name="__main__")

after = GRADLE.read_text()
checks = {
    "versionCode 310": "versionCode = 310" in after,
    "versionName 3.0.10": 'versionName = "3.0.10"' in after,
    "minSdk 26": "minSdk = 26" in after,
}

src = APP / "app" / "src" / "main" / "java" / "com" / "multyfi" / "intraday" / "mobile"
source_checks = {
    "MarketDataGuard": (src / "MarketDataGuard.kt").exists(),
    "3-tick confirmation": "ENTRY_CONFIRMATIONS = 3" in (src / "PaperEngine.kt").read_text(),
    "90-second cooldown": "REENTRY_COOLDOWN_MS = 90_000L" in (src / "PaperEngine.kt").read_text(),
    "volume regression guard": "VOLUME_REGRESSION" in (src / "MarketDataGuard.kt").read_text(),
    "feed degraded protection": "FEED DEGRADED" in (src / "MultyfiNotificationService.kt").read_text(),
    "feed recovery protection": "FEED RECOVERED" in (src / "MultyfiNotificationService.kt").read_text(),
}

failed = [name for name, ok in {**checks, **source_checks}.items() if not ok]
if failed:
    raise SystemExit("V3.0.10 source verification failed: " + ", ".join(failed))

print("Multyfi Intraday Mobile V3.0.10 source generated and verified.")
print("Package: com.multyfi.intraday.mobile")
print("Version: 3.0.10 (310)")
print("minSdk: 26")
print("Live Buy & Sell default: OFF")
