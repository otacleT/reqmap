# -*- coding: utf-8 -*-
import os
import shutil
import subprocess
import tempfile
import unittest

from helpers import CLI, make_vault, page

SPEC = """// @area: A-01
requirements OrderStatus {
  process Order {
    stages Draft, Paid, Preparing, Cancelled
    initial Draft
    transition pay Draft -> Paid by Customer covers REQ-O-001 "支払"
    transition cancel Draft -> Cancelled by Customer covers REQ-O-002 "取消"
    transition accept Paid -> Preparing by Shop covers REQ-O-003 "受注"
  }
  forbidden FB-O-001 "二重決済" {
    pay(0) pay(0)
    expect rejected
  }
  terminal { forall c: Order { stage(c) == Preparing or stage(c) == Cancelled } }
}
verify { instances Order = 2 }
"""


def view(root):
    r = subprocess.run([CLI, "view", "--root=%s" % root], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return open(os.path.join(root, ".reqmap", "index.html"), encoding="utf-8").read()


class ViewTest(unittest.TestCase):
    def test_view_builds_without_specs(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_vault(tmp)
            page(tmp, "a", "A")
            html = view(tmp)
            self.assertIn("状態×イベント", html)
            self.assertIn("要件の地図", html)

    @unittest.skipIf(shutil.which("fslc") is None, "fslc がありません")
    def test_view_embeds_the_matrix(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_vault(tmp)
            with open(os.path.join(tmp, "models", "fsl", "order.fsl"), "w", encoding="utf-8") as f:
                f.write(SPEC)
            html = view(tmp)
            self.assertIn("fsl/order", html)
            self.assertIn('"forbidden"', html)
            self.assertIn('"hole"', html)


if __name__ == "__main__":
    unittest.main()
