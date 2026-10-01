#!/bin/zsh
set -euo pipefail
SRC="$(cd "$(dirname "$0")" && pwd)"
APP="$HOME/Applications/PS_Scanner_Final"
LABEL="com.psscanner.final"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
TS="$(date +%Y%m%d_%H%M%S)"
ROLLBACK="$HOME/Applications/PS_Scanner_Final.rollback.$TS"
TMPSECRET="$(mktemp)"
OLD_STATUS="$(mktemp)"
NEW_HEALTH="$(mktemp)"
NEW_GROWW="$(mktemp)"
PLIST_BACKUP="$(mktemp)"
HAD_OLD_PLIST=0
MODE="migration"
cleanup(){ rm -f "$TMPSECRET" "$OLD_STATUS" "$NEW_HEALTH" "$NEW_GROWW" "$PLIST_BACKUP" 2>/dev/null || true; }
trap cleanup EXIT

echo "PS Scanner Quant v6.6.1 safe install / in-place upgrade"
echo "Target: $APP"
echo

if [[ ! -d "$APP" ]]; then
  echo "Previous PS_Scanner_Final not found; refusing install because Groww credential preservation cannot be verified." >&2
  exit 10
fi

if [[ -f "$APP/psscanner_quant/constants.py" ]] && grep -q 'VERSION = "6\.' "$APP/psscanner_quant/constants.py" 2>/dev/null; then
  MODE="upgrade"
fi

echo "Detected mode: $MODE"

if curl -fsS --max-time 5 http://127.0.0.1:8765/api/health > "$OLD_STATUS" 2>/dev/null; then
  python3 - "$OLD_STATUS" <<'PY'
import json,sys
try:d=json.load(open(sys.argv[1]))
except Exception:d={}
g=d.get("groww") or {}
print("Existing app:", d.get("app") or "UNKNOWN", d.get("version") or "")
print("Existing Groww status:", g.get("status") or "UNKNOWN", "auth_mode:", g.get("auth_mode") or "UNKNOWN")
PY
fi

# In a v6->v6 upgrade, the entire data directory is the authoritative state: credentials,
# settings, recommendation ledger, strategy statistics, feature/history caches and audit data.
# In a legacy migration, recover only a validated coherent Groww credential bundle.
if [[ "$MODE" == "migration" ]]; then
  "$SRC/tools/migrate_groww_secrets.py" "$APP" "$TMPSECRET"
  chmod 600 "$TMPSECRET"
  python3 - "$TMPSECRET" <<'PY'
import json,sys
p=json.load(open(sys.argv[1]))
print("Validated Groww auth mode:", p.get("auth_mode") or "unknown")
print("Recovered credential capabilities:", ", ".join(k for k in ("api_key","api_secret","totp_token","totp_secret","access_token") if p.get(k)))
print("Secret values: hidden")
PY
fi

if [[ -f "$PLIST" ]]; then
  cp "$PLIST" "$PLIST_BACKUP"
  HAD_OLD_PLIST=1
fi

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
sleep 1
mv "$APP" "$ROLLBACK"
mkdir -p "$APP"

rollback(){
  echo "INSTALL FAILED — restoring previous application" >&2
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  rm -rf "$APP"
  if [[ -d "$ROLLBACK" ]]; then mv "$ROLLBACK" "$APP"; fi
  if [[ $HAD_OLD_PLIST -eq 1 ]]; then
    cp "$PLIST_BACKUP" "$PLIST"
    plutil -lint "$PLIST" >/dev/null 2>&1 || true
    launchctl bootstrap "gui/$(id -u)" "$PLIST" 2>/dev/null || true
    launchctl kickstart -k "gui/$(id -u)/$LABEL" 2>/dev/null || true
  else
    rm -f "$PLIST"
  fi
}
trap 'rc=$?; if [[ $rc -ne 0 ]]; then rollback; fi; cleanup; exit $rc' EXIT

# Install code only. Runtime state is restored below, never seeded over existing v6 state.
rsync -a --delete --exclude '.venv' --exclude '__pycache__' --exclude '*.pyc' --exclude 'data' --exclude 'logs' "$SRC/" "$APP/"
mkdir -p "$APP/data/secure" "$APP/logs"

if [[ "$MODE" == "upgrade" ]]; then
  if [[ -d "$ROLLBACK/data" ]]; then rsync -a "$ROLLBACK/data/" "$APP/data/"; fi
  if [[ -d "$ROLLBACK/logs" ]]; then rsync -a "$ROLLBACK/logs/" "$APP/logs/"; fi
  echo "Preserved v6 data, credentials, settings, recommendation ledger and strategy state."
  # v6.4.3 settings migration: v6.3.2 changed the default observation gate to 1,
  # but preserved settings.json from older installs can still contain 6/4. Apply the
  # new morning-freeze contract before the regression suite runs. No other setting is touched.
  # IMPORTANT: run from $APP. Running this while cwd is the extracted source folder
  # lets Python import the source package first and migrate the wrong data/settings.json.
  (
    cd "$APP"
    PYTHONPATH="$APP" python3 - <<'PYSET'
from psscanner_quant.config import migrate_morning_freeze_settings
r = migrate_morning_freeze_settings()
print(
    "v6.4.3 settings migration — weekly_min_observations:",
    r.get("weekly_before"), "->", r.get("weekly_after"),
    "; monthly_min_observations:",
    r.get("monthly_before"), "->", r.get("monthly_after"),
)
if r.get("reason") == "INVALID_SETTINGS_JSON":
    print("v6.4.3 settings migration warning: preserved settings.json is invalid; runtime defaults will be used.")
PYSET
  )
  # Verify the target runtime file itself, independent of Python import resolution.
  python3 - "$APP/data/settings.json" <<'PYVERIFY'
import json,sys
from pathlib import Path
p=Path(sys.argv[1])
d={}
if p.exists():
    d=json.loads(p.read_text())
if d.get("weekly_min_observations") != 1 or d.get("monthly_min_observations") != 1:
    raise SystemExit("Morning Freeze settings migration did not update the target runtime file")
if any(d.get(k) != 0 for k in ("universe_size","intraday_scan_size","horizon_scan_size")):
    raise SystemExit("Full NSE breadth migration left a legacy scan-size cap active")
if d.get("full_nse_breadth_enabled") is not True:
    raise SystemExit("Full NSE breadth migration was not enabled in target settings")
print("v6.4.3 target settings verification: weekly=1 monthly=1 full_nse_breadth=true legacy_caps=0/0/0")
PYVERIFY
  # v6.4.3 lifecycle migration. Preserve every recommendation in the immutable ledger.
  # Horizon publication timing changes, but existing frozen recommendations remain valid.
  # Nothing is deleted; rollback remains untouched.
  python3 - "$APP/data/psscanner_quant.db" <<'PY2'
import sqlite3,sys
p=sys.argv[1]
try:
    con=sqlite3.connect(p)
    def close_where(where, reason):
        cur=con.execute(
            "UPDATE recommendations SET state='CLOSED',result='VOID',close_reason=?,closed_at=datetime('now'),updated_at=datetime('now') WHERE state='LIVE' AND " + where,
            (reason,),
        )
        return cur.rowcount
    # Old Circuit rows had no 15:00 same-session feasibility contract and must not leak
    # into the redesigned same-day/next-session lanes.
    c1=close_where("book='CIRCUIT' AND (rationale_json IS NULL OR rationale_json NOT LIKE '%SAME_SESSION_TARGET_BY_15_00_IST%')", 'V630_CIRCUIT_DEADLINE_RESET')
    # v6.4.3 publishes US equities LONG-only. Retain prior shorts for audit but prevent
    # them remaining executable/research-LIVE under the new policy.
    c2=close_where("book='INTERNATIONAL' AND side='SHORT'", 'V630_INTERNATIONAL_LONG_ONLY_RESET')
    # Any pre-v6.4.3 Indian intraday SHORT lacked the user's hard 15:00 lifecycle.
    c3=close_where("book='INTRADAY' AND side='SHORT' AND (rationale_json IS NULL OR rationale_json NOT LIKE '%15:00%')", 'V630_1500_SHORT_POLICY_RESET')
    # Older pre-v6.2.4 International rows may still exist on long-upgrade chains.
    c4=close_where("book='INTERNATIONAL' AND side='LONG' AND rationale_json LIKE '%US_REGULAR_SESSION_DAILY%'", 'V624_LEGACY_INTERNATIONAL_SESSION_RESET')
    # v6.4.3 replaces the remaining daily U.S.-session LIVE rows with a frozen weekly book.
    # Preserve them as auditable VOID rows; never reinterpret a daily target as a weekly target.
    c5=close_where("book='INTERNATIONAL' AND side='LONG' AND (rationale_json IS NULL OR rationale_json NOT LIKE '%US_WEEKLY_FROZEN_LONG_ONLY%')", 'V631_US_WEEKLY_RESET')
    # Indian multi-session books are delivery/holding books. SHORT rows cannot be carried
    # across sessions for this user, so retain them only as auditable research history.
    c6=close_where("book IN ('WEEKLY','MONTHLY','ETF') AND side='SHORT'", 'V638_HORIZON_SHORT_RESEARCH_ONLY_RESET')
    # v6.4.3 makes same-day Circuit recommendations fail closed unless fresh current-session
    # intraday evidence, known liquidity/volume and execution permission were verified.
    c7=close_where("book='CIRCUIT' AND (rationale_json IS NULL OR rationale_json NOT LIKE '%V642_FRESH_INTRADAY_LIQUIDITY_EXECUTION%')", 'V642_CIRCUIT_EVIDENCE_RESET')
    con.commit()
    print("v6.4.3 ledger migration — Circuit LIVE rows VOID:", c1)
    print("v6.4.3 ledger migration — International SHORT LIVE rows VOID:", c2)
    print("v6.4.3 ledger migration — Intraday SHORT LIVE rows VOID:", c3)
    print("Legacy International stale LIVE rows VOID:", c4)
    print("v6.4.3 ledger migration — remaining daily International LIVE rows VOID:", c5)
    print("v6.4.3 ledger migration — Weekly/Monthly/ETF SHORT LIVE rows VOID:", c6)
    print("v6.4.3 ledger migration — pre-evidence-gate Circuit LIVE rows VOID:", c7)
    con.close()
except Exception as exc:
    print("v6.4.3 ledger migration warning:",exc)
PY2
else
  cp "$TMPSECRET" "$APP/data/secure/groww_credentials.json"
  chmod 600 "$APP/data/secure/groww_credentials.json"
fi

cd "$APP"
python3 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip setuptools wheel
./.venv/bin/pip install -r requirements.txt
./.venv/bin/python -m compileall -q psscanner_quant
./.venv/bin/python -m unittest discover -s tests -v

mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>$LABEL</string>
<key>ProgramArguments</key><array><string>$APP/run.sh</string></array>
<key>WorkingDirectory</key><string>$APP</string>
<key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
<key>StandardOutPath</key><string>$APP/logs/service.log</string>
<key>StandardErrorPath</key><string>$APP/logs/service-error.log</string>
<key>ProcessType</key><string>Background</string>
</dict></plist>
EOF
plutil -lint "$PLIST"
launchctl bootstrap "gui/$(id -u)" "$PLIST"
launchctl kickstart -k "gui/$(id -u)/$LABEL"

ok=0
for i in {1..60}; do
  if curl -fsS --max-time 3 http://127.0.0.1:8765/api/health > "$NEW_HEALTH" 2>/dev/null; then
    if python3 - "$NEW_HEALTH" <<'PYH'
import json,sys
try:d=json.load(open(sys.argv[1]))
except Exception:d={}
ok=(d.get('version')=='6.6.1' and d.get('engine_alive') is True)
raise SystemExit(0 if ok else 1)
PYH
    then ok=1; break; fi
  fi
  sleep 2
done
if [[ $ok -ne 1 ]]; then
  echo "v6.6.1 service did not pass application health check. See $APP/logs/service-error.log" >&2
  exit 20
fi

groww_ok=0
groww_auth_required=0
for i in {1..12}; do
  if curl -fsS --max-time 20 'http://127.0.0.1:8765/api/groww/status?refresh=true' > "$NEW_GROWW" 2>/dev/null; then
    if python3 - "$NEW_GROWW" <<'PYG'
import json,sys
try:d=json.load(open(sys.argv[1]))
except Exception:d={}
print('Groww probe:', d.get('status') or 'UNKNOWN', 'connected:', bool(d.get('connected')))
raise SystemExit(0 if d.get('connected') is True else 1)
PYG
    then
      groww_ok=1
      break
    fi
    if python3 - "$NEW_GROWW" <<'PYA'
import json,sys
try:d=json.load(open(sys.argv[1]))
except Exception:d={}
raise SystemExit(0 if str(d.get('status') or '').upper()=='AUTH_REQUIRED' else 1)
PYA
    then groww_auth_required=$((groww_auth_required+1)); fi
  fi
  sleep 3
done

if [[ $groww_ok -ne 1 ]]; then
  echo "v6.6.1 application started, but Groww connectivity could not be verified after explicit probes." >&2
  if [[ $groww_auth_required -gt 0 ]]; then
    echo "Groww returned AUTH_REQUIRED during verification." >&2
  else
    echo "Groww probe never reached CONNECTED; refusing to discard rollback." >&2
  fi
  exit 21
fi

curl -fsS --max-time 5 http://127.0.0.1:8765/api/health > "$NEW_HEALTH" 2>/dev/null || true
python3 - "$NEW_HEALTH" "$NEW_GROWW" <<'PYV'
import json,sys
try:h=json.load(open(sys.argv[1]))
except Exception:h={}
try:g=json.load(open(sys.argv[2]))
except Exception:g={}
print('New app:', h.get('app'), h.get('version'))
print('New Groww status:', g.get('status') or 'UNKNOWN')
print('Credential capabilities:', g.get('credential_capabilities') or {})
ok=(h.get('version')=='6.6.1' and h.get('engine_alive') is True and g.get('connected') is True)
raise SystemExit(0 if ok else 1)
PYV

rm -rf "$ROLLBACK"
trap cleanup EXIT

echo
echo "============================================================"
echo "PS Scanner Quant v6.6.1 INSTALLED"
echo "UI: http://127.0.0.1:8765"
echo "Groww authentication: VERIFIED"
echo "v6 runtime data/ledger: PRESERVED"
echo "Weekly: current-period frozen book; preferred freeze 09:00-09:12 IST; deterministic missed-freeze recovery without gate relaxation"
echo "Monthly: current-period frozen book; pre-month preferred; no hindsight reconstruction of effectively expired periods"
echo "No rank replacement; no backfill after close"
echo "NSE stock universe: all NSE equity-share series from Groww (main board + trade-for-trade + SME + partly-paid); debt/funds/REIT/InvIT/warrants/ETFs excluded from stock scans"
echo "New listings: discovered automatically on instrument-master refresh; limited-history names remain visible and are prioritized for cache warm-up"
echo "Manual order maximum notional: ₹20,000"
echo "Risk-to-stop cap: ₹500 (quantity may be reduced)"
echo "Handbook layer: 100 strategy families + 50 candles + 50 intelligence filters"
echo "Evidence layer: full NSE instrument master + point-in-time fundamentals + NSE calendar + sector breadth + event gates"
echo "Research safety: live-shadow Challengers required for promotion"
echo "Execution audit: Groww order/fill reconciliation enabled"
echo "History reliability: Groww max-window-aware chunking + paced requests + adaptive 429 backoff"
echo "History contract: 1day <=175-day chunks; 5minute <=30-day requests; false legacy daily-400 quarantines auto-cleared"
echo "History parser: mixed Groww ISO/epoch cache formats normalized; existing raw caches reused"
echo "History priority: live/frozen + new listings -> missing caches -> full NSE rotating background -> ETFs"
echo "Scheduler: dynamic NSE instrument refresh + full-breadth batched LTP discovery + independent cache-first research workers"
echo "Intraday: current-session only; SHORT ends by 15:00 IST; unresolved LONG resolves at NSE session end/rollover"
echo "Circuit live: same-session calls require target feasibility by 15:00 + fresh intraday bars + known liquidity/volume + execution permission"
echo "Circuit 3PM: frozen LONG-only next-NSE-session upper-circuit watchlist at 15:00 IST"
echo "International: frozen US WEEKLY LONG-only stock/ETF book; no replacement/backfill; closes at target/stop/week end"
echo "Global->India: overnight provisional sector/cross-asset map scans full NSE breadth; LONG/SHORT board freezes after 09:00 IST"
echo "Research/API: active-period recommendations + /api/performance + /api/history/recommendations + /api/lifecycle (independent of Static IP)"
echo "Execution: Static IP mismatch disables order buttons only"
echo "Diagnostics: ./tools/run_diagnostics.sh"
echo "Post-install validation: python3 tools/post_install_validate.py"
echo "============================================================"
python3 - "$NEW_HEALTH" <<'PY'
import json,sys,urllib.request
h=json.load(open(sys.argv[1]))
out={"app":h.get("app"),"version":h.get("version"),"engine_alive":h.get("engine_alive"),"groww":h.get("groww"),"static_ip":h.get("static_ip"),"execution":h.get("execution"),"evidence":h.get("evidence")}
for book in ("WEEKLY","MONTHLY"):
    try:
        with urllib.request.urlopen("http://127.0.0.1:8765/api/book/"+book,timeout=5) as r:
            d=json.load(r)
        out[book.lower()]={"period_key":d.get("period_key"),"live_long":len((d.get("live") or {}).get("long") or []),"live_short":len((d.get("live") or {}).get("short") or []),"policy":d.get("policy")}
    except Exception as exc:
        out[book.lower()]={"error":str(exc)}
print(json.dumps(out,indent=2,default=str))
PY
