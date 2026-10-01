import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from psscanner_quant import db as dbmod
from psscanner_quant import history_control
from psscanner_quant import main
from psscanner_quant import orders


class V671HealthReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.old_db=dbmod.DB_PATH
        self.old_history_state=history_control._STATE_PATH
        self.tmp=tempfile.TemporaryDirectory()
        root=Path(self.tmp.name)
        dbmod.DB_PATH=root/"psscanner_quant.db"
        history_control._STATE_PATH=root/"history_control.json"
        dbmod.init_db()

    def tearDown(self):
        dbmod.DB_PATH=self.old_db
        history_control._STATE_PATH=self.old_history_state
        self.tmp.cleanup()

    def _hold_history_lock(self):
        acquired=threading.Event()
        release=threading.Event()
        def holder():
            with history_control._LOCK:
                acquired.set()
                release.wait(3)
        t=threading.Thread(target=holder,daemon=True)
        t.start()
        self.assertTrue(acquired.wait(1))
        return release,t

    def test_cached_history_status_never_waits_for_pacer(self):
        release,t=self._hold_history_lock()
        try:
            started=time.monotonic()
            out=history_control.status_cached()
            elapsed=time.monotonic()-started
            self.assertLess(elapsed,.25)
            self.assertTrue(out["pacer_busy"])
            self.assertTrue(out["nonblocking"])
            self.assertEqual(out["status"],"PACER_BUSY_NONBLOCKING_SNAPSHOT")
        finally:
            release.set();t.join(1)

    def test_health_returns_while_history_pacer_lock_is_busy(self):
        release,t=self._hold_history_lock()
        try:
            started=time.monotonic()
            out=main.health()
            elapsed=time.monotonic()-started
            self.assertLess(elapsed,2.0)
            self.assertEqual(out["version"],"6.7.1")
            self.assertFalse(out["health_contract"]["network_calls"])
            self.assertTrue(out["health_contract"]["history_pacer_nonblocking"])
            self.assertTrue(out["evidence"]["history_control"]["pacer_busy"])
        finally:
            release.set();t.join(1)

    def test_cached_execution_readiness_fails_fast_when_order_count_unavailable(self):
        with patch.object(orders,"db",side_effect=RuntimeError("database busy")):
            started=time.monotonic()
            out=orders.execution_readiness(use_cached=True)
            elapsed=time.monotonic()-started
        self.assertLess(elapsed,1.0)
        self.assertIsNone(out["today_manual_orders"])
        self.assertIn("daily_order_count_unavailable",out["blockers"])

    def test_validator_has_retries_and_initializes_new_v670_checks(self):
        src=(Path(__file__).resolve().parents[1]/"tools"/"post_install_validate.py").read_text()
        self.assertIn("attempts=4",src)
        self.assertIn('diag=get("/api/diagnostics/no-trade?limit=4"',src)
        self.assertIn('execution=get("/api/execution/analytics?limit=20"',src)
        self.assertIn('backups=get("/api/maintenance/backups"',src)
        self.assertIn('"V671_NONBLOCKING_HEALTH_AND_VALIDATION"',src)


if __name__=="__main__":
    unittest.main()
