import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from psscanner_quant import analytics, db as dbmod, execution_integrity as xi, production_integrity as pi
from psscanner_quant.constants import VERSION
from psscanner_quant.lifecycle import lifecycle_payload


class V670ProductionIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.old_db=dbmod.DB_PATH
        self.old_pi_db=pi.DB_PATH
        self.old_backup=pi.BACKUP_DIR
        self.tmp=tempfile.TemporaryDirectory()
        root=Path(self.tmp.name)
        dbmod.DB_PATH=root/"psscanner_quant.db"
        pi.DB_PATH=dbmod.DB_PATH
        pi.BACKUP_DIR=root/"backups"
        dbmod.init_db()

    def tearDown(self):
        dbmod.DB_PATH=self.old_db
        pi.DB_PATH=self.old_pi_db
        pi.BACKUP_DIR=self.old_backup
        self.tmp.cleanup()

    def _closed(self, rid, ts, result="WIN", current=102.0):
        with dbmod.db() as con:
            con.execute(
                """INSERT INTO recommendations(
                    recommendation_id,book,period_key,symbol,exchange,side,state,score,confidence,
                    entry_price,current_price,target_price,stop_price,target_pct,horizon,regime,
                    created_at,updated_at,closed_at,result,close_reason
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (rid,"INTRADAY",ts[:10],rid,"NSE","LONG","CLOSED",80,.8,100,current,102,99,2,
                 "INTRADAY","RANGE",ts,ts,ts,result,"TEST"),
            )

    def test_version_and_lifecycle(self):
        self.assertEqual(VERSION,"6.7.0")
        self.assertEqual(lifecycle_payload()["policy_version"],"V670_PRODUCTION_INTEGRITY_AND_REPLAY")

    def test_schema_additive_integrity_tables_and_columns_exist(self):
        with dbmod.db() as con:
            tables={r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            rec={r[1] for r in con.execute("PRAGMA table_info(recommendations)")}
            dec={r[1] for r in con.execute("PRAGMA table_info(trade_decisions)")}
            orders={r[1] for r in con.execute("PRAGMA table_info(orders)")}
        self.assertTrue({"scan_runs","experiments"}.issubset(tables))
        self.assertTrue({"software_version","config_hash","decision_id","audit_envelope_json"}.issubset(rec))
        self.assertTrue({"audit_envelope_json","pipeline_verdict","pipeline_stage"}.issubset(dec))
        self.assertTrue({"decision_price","decision_ts","submitted_at","execution_metrics_json","margin_check_json","cost_estimate_json","position_reconcile_json"}.issubset(orders))

    def test_audit_envelope_is_point_in_time_and_secret_free(self):
        env=pi.make_audit_envelope("INTRADAY","2026-10-01","ABC","LONG",
                                   {"close":100,"asof":"2026-10-01T10:00:00+05:30"},
                                   {"data_confidence":.9},[])
        self.assertEqual(env["software_version"],"6.7.0")
        self.assertEqual(env["audit_policy"],"V670_POINT_IN_TIME_PRODUCTION_ENVELOPE")
        self.assertTrue(env["settings_hash"])
        raw=json.dumps(env).lower()
        self.assertNotIn("api_secret",raw)
        self.assertNotIn("access_token",raw)

    def test_scan_run_persists_rejection_funnel(self):
        rid=pi.record_scan_run("INTRADAY",{
            "started_at":"2026-10-01T09:30:00+05:30","completed_at":"2026-10-01T09:31:00+05:30",
            "target_period_key":"2026-10-01","stage":"DONE","processed":10,"universe":10,
            "full_nse_universe":100,"near_misses":[{"symbol":"ABC","rejection_stage":"SCORE"}],
            "funnel":{"universe_total":100,"scan_scope_total":10,"scan_scope_processed":10,"score_reject":4},
        })
        with dbmod.db() as con:
            row=con.execute("SELECT * FROM scan_runs WHERE run_id=?",(rid,)).fetchone()
        self.assertEqual(row["universe_total"],100)
        self.assertEqual(json.loads(row["funnel_json"])["score_reject"],4)

    def test_replay_uses_stored_inputs_and_does_not_invent_legacy_context(self):
        payload={"symbol":"ABC","side":"LONG","strategies":["S1"],
                 "trade_intelligence":{"decision":"ELIGIBLE","hard_fail_count":0},
                 "pipeline_verdict":"PUBLICATION_READY","pipeline_stage":"FINAL_GATES"}
        env={"audit_policy":"V670_POINT_IN_TIME_PRODUCTION_ENVELOPE","software_version":"6.7.0"}
        with dbmod.db() as con:
            con.execute(
                "INSERT INTO trade_decisions(decision_id,ts,book,period_key,symbol,side,decision,ensemble_score,intelligence_score,hard_fail_count,"
                "strategy_ids_json,payload_json,audit_envelope_json,pipeline_verdict,pipeline_stage) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("D1","2026-10-01T10:00:00+05:30","INTRADAY","2026-10-01","ABC","LONG","ELIGIBLE",80,80,0,
                 '["S1"]',json.dumps(payload),json.dumps(env),"PUBLICATION_READY","FINAL_GATES"))
        out=pi.replay_decisions("D1",10)["rows"][0]
        self.assertEqual(out["input_replayability"],"PROSPECTIVE_COMPLETE")
        self.assertEqual(out["replayed"]["verdict"],"PUBLICATION_READY")
        self.assertTrue(out["contract_match"])

    def test_broker_position_mismatch_hard_blocks(self):
        with patch.object(xi.broker,"positions",return_value={"positions":[
            {"trading_symbol":"ABC","product":"MIS","quantity":-1,"net_carry_forward_quantity":0,"realised_pnl":0}
        ]}):
            out=xi.reconcile_positions()
        self.assertTrue(out["verified"])
        self.assertTrue(out["hard_block"])
        self.assertEqual(out["external_session_positions"][0]["symbol"],"ABC")

    def test_dynamic_short_margin_permission_and_positive_net_edge(self):
        rec={"symbol":"ABC","side":"SHORT","exchange":"NSE","target_pct":2.0}
        plan={"product":"MIS","quantity":10,"limit_price":100.0,"estimated_notional":1000.0}
        quality={"spread_pct":.10}
        with patch.object(xi,"reconcile_positions",return_value={"verified":True,"hard_block":False,"mismatches":[]}), \
             patch.object(xi.broker,"required_margin",return_value={"cash_mis_margin_required":100.0,"brokerage_and_charges":2.0,"total_requirement":100.0}), \
             patch.object(xi.broker,"available_margin",return_value={"equity_margin_details":{"mis_balance_available":1000.0}}):
            out=xi.pretrade_permission(rec,plan,quality)
        self.assertTrue(out["ready"])
        self.assertEqual(out["margin"]["shortability"],"BROKER_MIS_MARGIN_VALIDATED")
        self.assertGreater(out["costs"]["expected_net_edge_rupees"],0)

    def test_execution_metrics_separate_slippage_and_latency(self):
        order={"side":"LONG","decision_price":100.0,"limit_price":100.2,
               "decision_ts":"2026-10-01T10:00:00.000+05:30","submitted_at":"2026-10-01T10:00:00.200+05:30",
               "acknowledged_at":"2026-10-01T10:00:00.400+05:30"}
        fills=[{"quantity":10,"price":100.1,"exchange_time":"2026-10-01T10:00:00.600+05:30"}]
        m=xi.order_execution_metrics(order,fills)
        self.assertAlmostEqual(m["decision_slippage_bps"],10.0,places=2)
        self.assertEqual(m["decision_to_submit_ms"],200.0)
        self.assertEqual(m["decision_to_first_fill_ms"],600.0)

    def test_time_of_day_cohort_is_shadow_only_at_tiny_sample(self):
        self._closed("OPEN","2026-10-01T09:30:00+05:30","WIN",102)
        p=analytics.performance(group_by="time_bucket")
        g=next(x for x in p["groups"] if x["group"]=="OPENING_0915_1000")
        self.assertFalse(g["live_use_eligible"])
        self.assertFalse(g["live_use_gate"]["automatic_activation"])

    def test_backup_is_restore_verified_without_touching_live_ledger(self):
        with dbmod.db() as con:
            con.execute("INSERT INTO system_state(key,value_json,updated_at) VALUES('X','{}','2026-10-01T10:00:00+05:30')")
        out=pi.backup_database(force=True,retention=2)
        self.assertTrue(out["restore_verified"])
        self.assertEqual(out["quick_check"],"ok")
        self.assertTrue(Path(out["path"]).exists())
        with dbmod.db() as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM system_state WHERE key='X'").fetchone()[0],1)

    def test_experiment_registry_requires_explicit_hypothesis_and_rollback(self):
        pi.seed_release_experiment()
        rows=pi.experiments()
        row=next(x for x in rows if x["experiment_id"]=="EXP-V670-PRODUCTION-INTEGRITY")
        self.assertTrue(row["hypothesis"])
        self.assertTrue(row["sample_requirement"])
        self.assertTrue(row["rollback_criterion"])


if __name__=="__main__":
    unittest.main()
