#!/bin/bash
set -euo pipefail
ROOT="${1:-$HOME/Applications/PS_Scanner_Final}"
BASE="http://127.0.0.1:8765"

echo "=== PS Scanner 6.8.25 verifier ==="
python3 - "$ROOT" <<'PY'
import sys
from pathlib import Path
root=Path(sys.argv[1])
checks=[
 ("version",root/"psscanner_quant/constants.py",'VERSION = "6.8.25"'),
 ("book policy",root/"psscanner_quant/book_policy.py","V6824_CANONICAL_BOOK_EXECUTION_AND_PRESENTATION_POLICY"),
 ("preview drift",root/"psscanner_quant/orders.py","V6824_PREVIEW_PRICE_DRIFT_REVALIDATION"),
 ("runtime monitor",root/"psscanner_quant/runtime_reliability.py","V6825_RUNTIME_RELIABILITY_AND_DATA_QUALITY_PASSIVE"),
 ("history pacing",root/"psscanner_quant/history_control.py","V6825_ADAPTIVE_HISTORY_PRESSURE_PACING"),
 ("runtime routes",root/"psscanner_quant/main.py","V6825_RUNTIME_ENDPOINTS_AND_MONITOR"),
 ("runtime js",root/"static/ps_runtime_6825.js","PS_RUNTIME_RELIABILITY_V6825"),
 ("runtime css",root/"static/ps_runtime_6825.css","PS_RUNTIME_RELIABILITY_V6825"),
]
for name,p,marker in checks:
    ok=p.exists() and marker in p.read_text(errors="ignore")
    print(name+":", "PASS" if ok else "FAIL")
    if not ok: raise SystemExit(1)
PY

echo
echo "=== Runtime APIs ==="
curl -fsS "$BASE/api/ping"; echo
curl -fsS "$BASE/api/runtime/reliability"; echo
curl -fsS "$BASE/api/data-quality"; echo
curl -fsS "$BASE/api/runtime/session-ledger?limit=3"; echo

echo
echo "=== Static assets ==="
for u in "/static/ps_runtime_6825.css?v=6825" "/static/ps_runtime_6825.js?v=6825"; do
  code="$(curl -sS -o /dev/null -w '%{http_code}' "$BASE$u")"
  echo "$u -> HTTP $code"
  test "$code" = "200" || test "$code" = "304"
done

echo
echo "PASS: 6.8.25 runtime reliability/data-quality layer is active."
echo "Execution may still be LOCKED when an existing safety gate blocks it."
