# -*- coding: utf-8 -*-
"""README の「仕込んだ欠陥 → 検出されるチェック」の表を、そのまま回帰テストにする。"""
import shutil
import subprocess
import unittest

from helpers import CLI, EXAMPLE
from reqmap import changeset, gaps, model

EXPECTED = ["assumption.stale", "graph.unsound_decision", "graph.isolated",
            "graph.provisional_gate", "rule.dropped_has_edge", "grid.row_empty", "grid.empty",
            "grid.not_itemised", "rule.decided_without_rationale", "turn.no_response",
            "turn.reasked", "turn.churn", "rule.stale_link_text"]
EXPECTED_FSL = ["fsl.state_event_hole", "fsl.unused_event", "fsl.forbidden_accepted",
                "fsl.undecided_unlinked"]


class ExampleVaultTest(unittest.TestCase):
    def setUp(self):
        self.proj = model.Project(EXAMPLE)
        self.out = gaps.run(self.proj)
        self.checks = {f["check"] for f in self.out["findings"]}

    def test_planted_defects_are_detected(self):
        for c in EXPECTED:
            self.assertIn(c, self.checks, c)

    @unittest.skipIf(shutil.which("fslc") is None, "fslc がありません")
    def test_planted_fsl_defects_are_detected(self):
        for c in EXPECTED_FSL:
            self.assertIn(c, self.checks, c)
        self.assertNotIn("fsl.spec_error", self.checks)
        self.assertNotIn("fsl.legacy_format", self.checks)

    def test_review_blocks_the_hallucinated_quote(self):
        gates = [r["gate"] for f in changeset.changesets(self.proj)
                 for r in changeset.review(self.proj, f)[1]]
        self.assertEqual(gates.count(changeset.BLOCKED), 1)

    def test_every_command_exits_zero(self):
        for cmd in (["doctor"], ["status"], ["gaps"], ["review"], ["recalc", "--check"],
                    ["changes"], ["json"]):
            r = subprocess.run([CLI] + cmd + ["--root=%s" % EXAMPLE], capture_output=True, text=True)
            self.assertIn(r.returncode, (0, 1), "%s: %s" % (cmd, r.stderr[-300:]))
            self.assertEqual(r.stderr, "", "%s: %s" % (cmd, r.stderr[-300:]))

    @unittest.skipIf(shutil.which("fslc") is None, "fslc がありません")
    def test_doctor_reports_fslc(self):
        r = subprocess.run([CLI, "doctor", "--root=%s" % EXAMPLE], capture_output=True, text=True)
        self.assertIn("fslc", r.stdout)


if __name__ == "__main__":
    unittest.main()
