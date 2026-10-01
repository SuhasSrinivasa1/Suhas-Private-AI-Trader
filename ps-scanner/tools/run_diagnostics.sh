#!/bin/zsh
set -euo pipefail

APP="${1:-$HOME/Applications/PS_Scanner_Final}"
cd "$APP" || exit 1
TS=$(date +%Y%m%d_%H%M%S)
DIR="$HOME/Desktop/PS_Scanner_v630_Audit_$TS"
mkdir -p "$DIR/api"

echo "Collecting PS Scanner Quant v6.3.8 diagnostics into:"
echo "$DIR"

{
  echo "============================================================"
  echo "PS SCANNER QUANT v6.3.8 — SYSTEM"
  echo "============================================================"
  date
  echo
  echo "===== PROCESS ====="
  ps aux | grep -E '[u]vicorn.*psscanner|[P]ython.*psscanner' || true
  echo
  echo "===== PORT 8765 ====="
  lsof -nP -iTCP:8765 -sTCP:LISTEN 2>&1 || true
  echo
  echo "===== LAUNCHD ====="
  launchctl print gui/$(id -u)/com.psscanner.final 2>&1 || true
} > "$DIR/system.txt"

python3 - "$DIR" <<'PY'
import json,sys,urllib.request,urllib.error
from pathlib import Path
from datetime import datetime
root=Path(sys.argv[1]);api=root/'api'
endpoints=[
 '/api/ping','/api/health','/api/research/readiness','/api/recommendations','/api/execution/readiness','/api/settings','/api/history/status',
 '/api/book/INTRADAY','/api/book/WEEKLY','/api/book/MONTHLY','/api/book/ETF','/api/book/CIRCUIT','/api/book/CIRCUIT_NEXTDAY','/api/book/INTERNATIONAL','/api/book/GLOBAL_INDIA_LONG','/api/book/GLOBAL_INDIA_SHORT',
 '/api/circuit/board','/api/international/board','/api/global/markets','/api/workers','/api/scan/status','/api/history/coverage?limit=80&interval=1day&minimum_rows=30',
 '/api/regime','/api/strategy-lab','/api/research-framework','/api/trade-decisions?limit=100','/api/evidence/status','/api/orders','/api/portfolio'
]
res={};errs={}
def get(ep):
    req=urllib.request.Request('http://127.0.0.1:8765'+ep,headers={'Cache-Control':'no-cache'})
    with urllib.request.urlopen(req,timeout=25) as r:return json.load(r)
for ep in endpoints:
    safe=ep.strip('/').replace('/','__').replace('?','__').replace('&','_').replace('=','-')
    try:
        d=get(ep);res[ep]=d;(api/f'{safe}.json').write_text(json.dumps(d,indent=2,default=str))
    except Exception as e:
        errs[ep]=repr(e);(api/f'{safe}.ERROR.txt').write_text(repr(e))
h=res.get('/api/health',{});hist=res.get('/api/history/status',{});x=res.get('/api/execution/readiness',{})
def book(name):return res.get('/api/book/'+name,{})
def count(b,side):return len(((b.get('live') or {}).get(side) or []))
lines=[];A=lines.append
A('============================================================');A('PS SCANNER QUANT v6.3.8 — COMPACT SUMMARY');A('============================================================')
A('generated: '+datetime.now().isoformat(timespec='seconds'));A('')
A('===== API HEALTH =====');A(f'successful: {len(res)} / {len(endpoints)}');A(f'failed: {len(errs)}')
for ep,e in errs.items():A(f'ERROR {ep}: {e}')
A('');A('===== APP =====');A(f"version: {h.get('version')}");A(f"engine_alive: {h.get('engine_alive')}");A(f"engine_last_error: {h.get('engine_last_error')}")
g=h.get('groww') or {};A('');A('===== GROWW =====');A(f"status: {g.get('status')}");A(f"connected: {g.get('connected')}");A(f"auth_mode: {g.get('auth_mode')}")
ip=h.get('static_ip') or {};A('');A('===== STATIC IP =====');A(f"configured: {ip.get('configured')}");A(f"matches: {ip.get('matches')}");A(f"detected: {ip.get('detected')}")
rr=res.get('/api/research/readiness',{});A('');A('===== RESEARCH =====');A(f"ready: {rr.get('ready')}");A(f"recommendations_require_static_ip: {rr.get('recommendations_require_static_ip')}");A(f"static_ip_scope: {rr.get('static_ip_scope')}");A('');A('===== EXECUTION =====');A(f"ready: {x.get('ready')}");A(f"blockers: {x.get('blockers')}")
A('');A('===== HISTORY CONTROL =====');
for k in ('mode','minimum_request_interval_seconds','global_cooldown_remaining_seconds','consecutive_429','active_quarantines','rate_limit_events','invalid_request_events','successful_requests','last_rate_limit_at','last_success_at'):A(f'{k}: {hist.get(k)}')
for n in ('INTRADAY','WEEKLY','MONTHLY','ETF','CIRCUIT','CIRCUIT_NEXTDAY','INTERNATIONAL','GLOBAL_INDIA_LONG','GLOBAL_INDIA_SHORT'):
    b=book(n);A('');A(f'===== {n} =====');A(f"period: {b.get('period_key')}");A(f"long: {count(b,'long')}");A(f"short: {count(b,'short')}");A(f"closed: {len(b.get('closed') or [])}")
r=res.get('/api/regime',{});A('');A('===== REGIME =====');A(f"regime: {r.get('regime')}");A(f"sample: {r.get('sample')}");A(f"stale: {r.get('stale')}")
sl=res.get('/api/strategy-lab',{});A('');A('===== STRATEGY LAB =====');A(f"strategy_configurations: {sl.get('strategy_configurations')}");A(f"status_counts: {sl.get('status_counts')}");A(f"shadow_signals: {sl.get('shadow_signals')}")
ev=res.get('/api/evidence/status',{});A('');A('===== EVIDENCE =====');A(json.dumps(ev,indent=2,default=str)[:8000])
(root/'summary.txt').write_text('\n'.join(lines));print('\n'.join(lines))
PY

{
 echo "============================================================"
 echo "DATABASE QUICK CHECK"
 echo "============================================================"
 if command -v sqlite3 >/dev/null 2>&1; then
   find data -type f -name '*.db' -print | while IFS= read -r db; do
     echo; echo "----- $db -----"; sqlite3 "$db" 'PRAGMA quick_check;' 2>&1 || true
   done
 else echo "sqlite3 CLI unavailable"; fi
} > "$DIR/databases.txt"

{
 echo "============================================================"
 echo "RECENT APPLICATION LOGS"
 echo "============================================================"
 find logs -maxdepth 2 -type f \( -name '*.log' -o -iname '*stdout*' -o -iname '*stderr*' \) -print 2>/dev/null | while IFS= read -r f; do
   echo; echo "################ $f ################"; tail -n 500 "$f" 2>&1 || true
 done
} > "$DIR/recent_logs.txt"

{
 echo "============================================================"
 echo "RECENT ERROR SCAN (APP LOGS ONLY; .venv EXCLUDED)"
 echo "============================================================"
 grep -RniE 'Traceback|ERROR|Exception|CRITICAL|HTTP 429|Too Many Requests|HTTP 400|Bad Request|timeout|stale|disconnect|AUTH_REQUIRED' logs data/history_control.json 2>/dev/null | tail -n 500 || true
} > "$DIR/error_scan.txt"

cat "$DIR/system.txt" "$DIR/summary.txt" "$DIR/databases.txt" "$DIR/error_scan.txt" "$DIR/recent_logs.txt" > "$DIR/FULL_AUDIT.txt"
tar -czf "$DIR.tar.gz" -C "$(dirname "$DIR")" "$(basename "$DIR")"
echo
echo "============================================================"
echo "DONE"
echo "Summary:    $DIR/summary.txt"
echo "Full audit: $DIR/FULL_AUDIT.txt"
echo "Archive:    $DIR.tar.gz"
echo "============================================================"
