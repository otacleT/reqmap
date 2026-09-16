# -*- coding: utf-8 -*-
import subprocess
import tempfile
import unittest

from helpers import CLI, make_vault, page


def status(root):
    r = subprocess.run([CLI, "status", "--root=%s" % root], capture_output=True, text=True)
    return r.stdout


class DerivesTest(unittest.TestCase):
    def test_derived_item_is_not_proposed_as_a_question(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_vault(tmp)
            page(tmp, "c", "C", status="decided", decision="Xにする。")
            page(tmp, "d", "Dは機械的に従属", derives=["c"])
            out = status(tmp)
            self.assertIn("機械的に決められるもの", out)
            head = out.split("機械的に決められるもの")[0]
            self.assertNotIn("Dは機械的に従属", head)


if __name__ == "__main__":
    unittest.main()
