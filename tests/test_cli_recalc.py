# -*- coding: utf-8 -*-
import subprocess
import tempfile
import unittest

from helpers import CLI, make_vault, page


class RecalcCycleNoticeTest(unittest.TestCase):
    def test_recalc_announces_cycle_nodes(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_vault(tmp)
            page(tmp, "x", "X", prereqs=["y"])
            page(tmp, "y", "Y", prereqs=["x"])
            page(tmp, "z", "Z")
            r = subprocess.run([CLI, "recalc", "--check", "--root=%s" % tmp],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr[-300:])
            # 既存の graph.cycle 経路表示ではなく、初期値に落とした論点の告知を見る
            self.assertIn("初期値", r.stdout)
            self.assertRegex(r.stdout, r"初期値.*x|x.*初期値")


if __name__ == "__main__":
    unittest.main()
