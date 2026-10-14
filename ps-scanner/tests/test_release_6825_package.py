from __future__ import annotations
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
PKG=ROOT/"releases"/"6.8.25-runtime-reliability"
INSTALLER=PKG/"apply_runtime_6825.py"

MAIN='''from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pathlib import Path
STATIC=Path(__file__).parent.parent/"static"
app=FastAPI()
app.mount("/static",StaticFiles(directory=str(STATIC)),name="static")
'''

HISTORY='''from __future__ import annotations
import time
from threading import RLock
from typing import Any,Dict,Optional
_LOCK=RLock()
_LAST_REQUEST_MONO=0.0
_GLOBAL_COOLDOWN_UNTIL=0.0
_CONSECUTIVE_429=0
def load_settings():return {"history_min_request_interval_seconds":1.25}
def wait_for_slot() -> float:
    global _LAST_REQUEST_MONO
    settings=load_settings()
    min_gap=max(0.25,float(settings.get("history_min_request_interval_seconds",1.25)))
    with _LOCK:
        now_wall=time.time();now_mono=time.monotonic()
        wait=max(0.0,_GLOBAL_COOLDOWN_UNTIL-now_wall,min_gap-(now_mono-_LAST_REQUEST_MONO))
        if wait>0:time.sleep(wait)
        _LAST_REQUEST_MONO=time.monotonic()
        return wait
def record_rate_limit(retry_after: Optional[str]=None) -> float:
    global _GLOBAL_COOLDOWN_UNTIL, _CONSECUTIVE_429
    with _LOCK:
        _CONSECUTIVE_429 += 1
        delay=5.0
        _GLOBAL_COOLDOWN_UNTIL=max(_GLOBAL_COOLDOWN_UNTIL,time.time()+delay)
        return delay
def record_success() -> None:
    global _CONSECUTIVE_429
    _CONSECUTIVE_429=max(0,_CONSECUTIVE_429-1)
def status_cached() -> Dict[str,Any]:return status()
def status() -> Dict[str,Any]:
    settings=load_settings()
    return {"minimum_request_interval_seconds": float(settings.get("history_min_request_interval_seconds", 1.25))}
'''

class Release6825PackageTests(unittest.TestCase):
    def make_app(self,root:Path):
        q=root/"psscanner_quant";s=root/"static"
        q.mkdir(parents=True);s.mkdir();(root/"data").mkdir()
        (q/"constants.py").write_text('VERSION = "6.8.24"\n')
        (q/"main.py").write_text(MAIN)
        (q/"history_control.py").write_text(HISTORY)
        (q/"book_policy.py").write_text('X="V6824_CANONICAL_BOOK_EXECUTION_AND_PRESENTATION_POLICY"\n')
        (q/"orders.py").write_text('X="V6824_PREVIEW_PRICE_DRIFT_REVALIDATION"\n')
        (s/"index.html").write_text("<html><head></head><body>mock</body></html>")

    def call(self,root:Path,*extra):
        return subprocess.run([sys.executable,str(INSTALLER),"--app-root",str(root),*extra],
                              text=True,capture_output=True,timeout=30)

    def test_package_python_compiles(self):
        for p in [INSTALLER,PKG/"runtime_reliability.py.payload",PKG/"export_support_6825.py.payload"]:
            compile(p.read_text(),str(p),"exec")

    def test_mock_6824_dry_run_apply_and_idempotency(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/"app";self.make_app(root)
            r=self.call(root,"--dry-run")
            self.assertEqual(r.returncode,0,r.stdout+r.stderr)
            self.assertIn("DRY-RUN PASS",r.stdout)
            r=self.call(root)
            self.assertEqual(r.returncode,0,r.stdout+r.stderr)
            self.assertIn('VERSION = "6.8.25"',(root/"psscanner_quant/constants.py").read_text())
            self.assertIn("V6825_RUNTIME_ENDPOINTS_AND_MONITOR",(root/"psscanner_quant/main.py").read_text())
            self.assertIn("V6825_ADAPTIVE_HISTORY_PRESSURE_PACING",(root/"psscanner_quant/history_control.py").read_text())
            self.assertTrue((root/"psscanner_quant/runtime_reliability.py").exists())
            self.assertIn("ps_runtime_6825.js",(root/"static/index.html").read_text())
            r=self.call(root,"--dry-run")
            self.assertEqual(r.returncode,0,r.stdout+r.stderr)

if __name__=="__main__":
    unittest.main()
