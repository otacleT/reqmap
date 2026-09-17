# -*- coding: utf-8 -*-
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from helpers import CLI, make_vault, page

SPEC = '''requirements S {
  process Order {
    stages Draft, Paid
    initial Draft
    transition pay Draft -> Paid by Customer covers REQ-S-001 "支払"
  }
  forbidden FB-S-001 "二重決済" {
    pay(0) pay(0)
    expect rejected
  }
  terminal { forall c: Order { stage(c) == Paid } }
}
verify { instances Order = 1 }
'''


def ci(root, *extra, env=None):
    r = subprocess.run([sys.executable, CLI, "ci", "--root=%s" % root] + list(extra),
                       capture_output=True, text=True, env=env)
    return r.returncode, r.stdout


class CiTest(unittest.TestCase):
    def test_conflict_fails_the_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_vault(tmp)
            page(tmp, "c", "C", status="decided", decision="X。")
            page(tmp, "e", "E", status="decided", decision="Y。", conflicts=["c"])
            code, out = ci(tmp)
            self.assertEqual(code, 1, out)
            self.assertIn("graph.conflict", out)

    def test_clean_vault_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_vault(tmp)
            page(tmp, "a", "A")   # graph.isolated は出るがゲート対象ではない
            code, out = ci(tmp)
            self.assertEqual(code, 0, out)
            self.assertIn("通過", out)

    def test_gate_is_configurable(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_vault(tmp, extra_cfg="ci_gate:\n  - graph.isolated")
            page(tmp, "a", "A")
            code, out = ci(tmp)
            self.assertEqual(code, 1, out)
            self.assertIn("graph.isolated", out)

    @unittest.skipIf(shutil.which("fslc") is None, "fslc がありません")
    def test_missing_fslc_fails_unless_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_vault(tmp)
            with open(os.path.join(tmp, "models", "fsl", "s.fsl"), "w", encoding="utf-8") as f:
                f.write(SPEC)
            env = dict(os.environ, PATH="/nonexistent")
            code, out = ci(tmp, env=env)
            self.assertEqual(code, 1, out)
            self.assertIn("fsl.tool_missing", out)
            code, out = ci(tmp, "--allow-missing-fslc", env=env)
            self.assertEqual(code, 0, out)


if __name__ == "__main__":
    unittest.main()
