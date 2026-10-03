import inspect
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from psscanner_quant import db as dbmod
from psscanner_quant import execution_integrity as xi
from psscanner_quant import main
from psscanner_quant.broker import GrowwBroker
from psscanner_quant.constants import VERSION
from psscanner_quant.lifecycle import lifecycle_payload


class V673ExecutionCacheTests(unittest.TestCase):
    def setUp(self):
        self.old_db=dbmod.DB_PATH
        self.tmp=tempfile.TemporaryDirectory()
        dbmod.DB_PATH=Path(self.tmp.name)/"psscanner_quant.db"
        dbmod.init_db()

    def tearDown(self):
        dbmod.DB_PATH=self.old_db
        self.tmp.cleanup()

    def test_version_and_policy(self):
        self.assertEqual(VERSION,"6.8.2")
        self.assertEqual(lifecycle_payload()["policy_version"],"V680_SHARED_EVIDENCE_FABRIC_ADAPTIVE_ALGORITHM")

    def test_public_ip_probe_falls_back_and_populates_cache(self):
        b=GrowwBroker()
        bad=MagicMock()
        bad.raise_for_status.side_effect=RuntimeError("ipify unavailable")
        good=MagicMock()
        good.raise_for_status.return_value=None
        good.text="203.0.113.8\n"
        with patch.object(b._session,"get",side_effect=[bad,good]):
            ip=b.detected_public_ip(force_refresh=True)
        self.assertEqual(ip,"203.0.113.8")
        cached=b.static_ip_status_cached()
        self.assertEqual(cached["detected"],"203.0.113.8")
        self.assertEqual(cached["provider"],"aws_checkip")
        self.assertIsNone(cached["last_error"])

    def test_cached_readiness_snapshot_has_no_db_or_network_calls(self):
        src=inspect.getsource(main.execution_readiness_cached_snapshot)
        self.assertNotIn("db(",src)
        self.assertNotIn("static_ip_status()",src)
        self.assertNotIn("broker.status()",src)

    def test_health_uses_one_bounded_db_snapshot(self):
        src=inspect.getsource(main.health)
        self.assertIn('"db_connections":1',src)
        self.assertIn("execution_readiness_cached_snapshot",src)
        self.assertNotIn("_cached_states(",src)
        self.assertNotIn("_bounded_evidence_db(",src)
        started=time.monotonic()
        out=main.health()
        self.assertLess(time.monotonic()-started,2.0)
        self.assertEqual(out["version"],"6.8.2")
        self.assertEqual(out["health_contract"]["db_connections"],1)
        self.assertFalse(out["health_contract"]["network_calls"])

    def test_position_mismatch_remains_fail_closed_with_explicit_semantics(self):
        row={
            "trading_symbol":"BIRLACABLE","product":"CNC","quantity":52,
            "net_carry_forward_quantity":0,"credit_quantity":52,"debit_quantity":0,
            "carry_forward_credit_quantity":0,"carry_forward_debit_quantity":0,
            "realised_pnl":0,
        }
        with patch.object(xi.broker,"positions",return_value={"positions":[row]}), \
             patch.object(xi,"_local_expected_session_positions",return_value={}):
            out=xi.reconcile_positions()
        self.assertTrue(out["hard_block"])
        self.assertEqual(out["mismatches"][0]["classification"],"EXTERNAL_CNC_SESSION_POSITION")
        self.assertEqual(out["mismatches"][0]["broker_session_quantity_formula"],"quantity - net_carry_forward_quantity")
        self.assertEqual(out["positions"][0]["credit_quantity"],52)
        self.assertIn("fail-closed",out["position_semantics"])

    def test_background_broker_probe_refreshes_static_ip_cache(self):
        from psscanner_quant import engine
        src=inspect.getsource(engine.Engine._broker_probe)
        self.assertIn("broker.status()",src)
        self.assertIn("broker.static_ip_status()",src)


if __name__=="__main__":
    unittest.main()
