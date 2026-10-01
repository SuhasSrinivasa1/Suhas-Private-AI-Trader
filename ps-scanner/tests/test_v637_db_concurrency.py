import inspect
import threading
import time
import unittest

from psscanner_quant.constants import VERSION
from psscanner_quant.db import db, set_state, get_state
import psscanner_quant.db as dbmod
import psscanner_quant.strategy_lab as lab


class V637DBConcurrencyTests(unittest.TestCase):
    def test_version(self):
        self.assertGreaterEqual(tuple(map(int, VERSION.split("."))), (6, 4, 3))

    def test_db_context_has_no_process_wide_python_lock(self):
        src=inspect.getsource(dbmod.db)
        self.assertNotIn("with _LOCK", src)

    def test_idle_connection_does_not_block_state_write(self):
        entered=threading.Event()
        release=threading.Event()
        def holder():
            with db() as con:
                con.execute("SELECT 1").fetchone()
                entered.set()
                release.wait(1.0)
        t=threading.Thread(target=holder,daemon=True)
        t.start(); self.assertTrue(entered.wait(.5))
        started=time.monotonic()
        set_state("v637_concurrency_probe", {"ok": True})
        elapsed=time.monotonic()-started
        release.set(); t.join(1.0)
        self.assertLess(elapsed, .25)
        self.assertEqual(get_state("v637_concurrency_probe",{}).get("ok"), True)

    def test_shadow_price_work_is_outside_write_context(self):
        src=inspect.getsource(lab.resolve_shadow_signals)
        self.assertIn("updates=[]", src)
        self.assertLess(src.index("updates=[]"), src.index("if updates:"))
        # _shadow_exit_price must be called before the write-only `if updates:` block.
        self.assertLess(src.index("_shadow_exit_price"), src.index("if updates:"))


if __name__ == '__main__':
    unittest.main()
