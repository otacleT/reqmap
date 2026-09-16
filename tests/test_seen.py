# -*- coding: utf-8 -*-
import subprocess
import tempfile
import unittest

from helpers import CLI, make_vault, page


def run(*a):
    return subprocess.run([CLI] + list(a), capture_output=True, text=True).stdout


class SeenTest(unittest.TestCase):
    def test_gaps_snapshot_does_not_move_decision_baseline(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_vault(tmp)
            page(tmp, "c", "C", status="decided", decision="Xにする。")
            run("changes", "--ack", "--root=%s" % tmp)
            page(tmp, "c", "C", status="decided", decision="Yに変えた。")
            run("gaps", "--snapshot", "--root=%s" % tmp)
            out = run("changes", "--root=%s" % tmp)
            self.assertIn("書き換わった決定 1 件", out)
            run("changes", "--ack", "--root=%s" % tmp)
            self.assertIn("書き換わった決定はありません", run("changes", "--root=%s" % tmp))

    def test_changes_without_baseline_points_to_ack(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_vault(tmp)
            page(tmp, "c", "C")
            self.assertIn("changes --ack", run("changes", "--root=%s" % tmp))

    def test_gaps_new_after_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_vault(tmp)
            page(tmp, "a", "A")
            run("gaps", "--snapshot", "--root=%s" % tmp)
            self.assertIn("新しく出た観点はありません", run("gaps", "--new", "--root=%s" % tmp))
            page(tmp, "b", "B")
            self.assertIn("graph.isolated", run("gaps", "--new", "--root=%s" % tmp))


if __name__ == "__main__":
    unittest.main()
