import inspect
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from psscanner_quant import db as dbmod
from psscanner_quant import main, production_integrity
from psscanner_quant.constants import VERSION
from psscanner_quant.lifecycle import lifecycle_payload


class V672BoundedSanityTests(unittest.TestCase):
    def setUp(self):
        self.old_db=dbmod.DB_PATH
        self.old_pi_db=production_integrity.DB_PATH
        self.old_backup=production_integrity.BACKUP_DIR
        self.tmp=tempfile.TemporaryDirectory()
        root=Path(self.tmp.name)
        dbmod.DB_PATH=root/"psscanner_quant.db"
        production_integrity.DB_PATH=dbmod.DB_PATH
        production_integrity.BACKUP_DIR=root/"backups"
        dbmod.init_db()

    def tearDown(self):
        dbmod.DB_PATH=self.old_db
        production_integrity.DB_PATH=self.old_pi_db
        production_integrity.BACKUP_DIR=self.old_backup
        self.tmp.cleanup()

    def test_version_and_policy(self):
        self.assertEqual(VERSION,"6.8.0")
        self.assertEqual(lifecycle_payload()["policy_version"],
                         "V680_SHARED_EVIDENCE_FABRIC_ADAPTIVE_ALGORITHM")

    def test_runtime_sanity_does_not_run_inline_quick_check(self):
        src=inspect.getsource(main.sanity)
        self.assertNotIn("PRAGMA quick_check",src)
        self.assertIn("set_progress_handler",src)
        self.assertIn("DEFERRED_TO_VERIFIED_BACKUP",src)
        started=time.monotonic()
        out=main.sanity()
        elapsed=time.monotonic()-started
        self.assertLess(elapsed,2.5)
        self.assertEqual(out["database_runtime_check"],"ok")
        self.assertTrue(out["database_runtime_checks_complete"])
        self.assertFalse(out["sanity_contract"]["deep_quick_check_inline"])

    def test_verified_backup_supplies_deep_database_integrity(self):
        result=production_integrity.backup_database(force=True,retention=2)
        self.assertTrue(result["restore_verified"])
        self.assertEqual(result["quick_check"],"ok")
        out=main.sanity()
        self.assertEqual(out["database_quick_check"],"ok")
        self.assertTrue(out["deep_database_integrity"]["verified"])

    def test_backup_status_is_bounded_when_state_db_is_unavailable(self):
        with patch.object(production_integrity,"db",side_effect=RuntimeError("busy")):
            started=time.monotonic()
            out=production_integrity.backup_status(.01)
            elapsed=time.monotonic()-started
        self.assertLess(elapsed,.5)
        self.assertEqual(out["last"]["status"],"CACHE_UNAVAILABLE_BOUNDED")
        self.assertFalse(out["last"]["restore_verified"])

    def test_validator_moves_deep_quick_check_to_backup_restore(self):
        src=(Path(__file__).resolve().parents[1]/"tools"/"post_install_validate.py").read_text()
        self.assertIn('sanity=get("/api/sanity",timeout=4,attempts=4)',src)
        self.assertIn('"/api/maintenance/backup-now",method="POST",timeout=120,attempts=1',src)
        self.assertIn('deep.get("restore_verified") is not True',src)
        self.assertNotIn('sanity.get("database_quick_check")!="ok"',src)


if __name__=="__main__":
    unittest.main()
