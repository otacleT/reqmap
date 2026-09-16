# -*- coding: utf-8 -*-
import os
import shutil
import tempfile
import unittest

from helpers import make_vault, page
from reqmap import fsl, model

BASE = '''// @area: A-01
requirements OrderStatus {
  process Order {
    stages Draft, PendingPayment, Paid, Cancelled
    initial Draft
    transition submit Draft -> PendingPayment by Customer covers REQ-O-001 "送信"
    transition pay PendingPayment -> Paid by Customer covers REQ-O-002 "支払"
    transition cancel PendingPayment -> Cancelled by Customer covers REQ-O-003 "取消"
    %(extra)s
  }
  forbidden FB-O-001 "二重決済は拒否" {
    submit(0) pay(0) %(last)s(0)
    expect rejected
  }
  terminal { forall c: Order { stage(c) == Paid or stage(c) == Cancelled } }
}
verify {
  instances Order = 2
}
'''
REFUND = 'transition refund Paid -> Cancelled by Shop covers REQ-O-005 "返金"'


def spec(root, text, name="order.fsl"):
    with open(os.path.join(root, "models", "fsl", name), "w", encoding="utf-8") as f:
        f.write(text)


def run(root):
    return fsl.gaps(model.Project(root))


def checks(root):
    return [f["check"] for f in run(root)[0]]


@unittest.skipIf(shutil.which("fslc") is None, "fslc がありません")
class RunTest(unittest.TestCase):
    def test_clean_spec_yields_only_matrix_findings(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_vault(tmp)
            spec(tmp, BASE % {"extra": "", "last": "pay"})
            F, summ = run(tmp)
            cs = [f["check"] for f in F]
            self.assertIn("fsl.state_event_hole", cs)
            self.assertNotIn("fsl.forbidden_accepted", cs)
            self.assertNotIn("fsl.spec_error", cs)
            self.assertNotIn("fsl.dead_end", cs)
            self.assertEqual(summ[0]["verify"], "verified")

    def test_later_decision_contradicting_forbidden(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_vault(tmp)
            spec(tmp, BASE % {"extra": 'transition repay Paid -> Paid by Customer covers REQ-O-004 "再決済"',
                              "last": "repay"})
            F, summ = run(tmp)
            hit = [f for f in F if f["check"] == "fsl.forbidden_accepted"]
            self.assertEqual(len(hit), 1)
            self.assertIn("FB-O-001", hit[0]["question"])
            self.assertIn("repay", hit[0]["question"])
            self.assertIn("FB-O-001", summ[0]["verify"])   # 要約にも何で止まったかを出す

    def test_parse_error_is_a_spec_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_vault(tmp)
            spec(tmp, "requirements Broken {\n  process Order {\n")
            cs = checks(tmp)
            self.assertIn("fsl.spec_error", cs)
            self.assertNotIn("fsl.state_event_hole", cs)

    def test_missing_terminal_is_a_dead_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_vault(tmp)
            spec(tmp, (BASE % {"extra": "", "last": "pay"}).replace(
                "  terminal { forall c: Order { stage(c) == Paid or stage(c) == Cancelled } }\n", ""))
            self.assertIn("fsl.dead_end", checks(tmp))

    def test_undecided_linked_to_open_question_is_silent(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_vault(tmp)
            page(tmp, "Q-006", "キャンセル")
            spec(tmp, BASE % {"extra": '@undecided("Q-006 返金条件")\n    ' + REFUND, "last": "pay"})
            cs = checks(tmp)
            self.assertNotIn("fsl.stale_undecided", cs)
            self.assertNotIn("fsl.undecided_unlinked", cs)

    def test_undecided_on_decided_question_is_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_vault(tmp)
            page(tmp, "Q-006", "キャンセル", status="decided", decision="返金する。")
            spec(tmp, BASE % {"extra": '@undecided("Q-006 返金条件")\n    ' + REFUND, "last": "pay"})
            self.assertIn("fsl.stale_undecided", checks(tmp))

    def test_undecided_without_question_is_unlinked(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_vault(tmp)
            spec(tmp, BASE % {"extra": '@undecided("返金条件が未定")\n    ' + REFUND, "last": "pay"})
            self.assertIn("fsl.undecided_unlinked", checks(tmp))

    def test_legacy_jssm_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_vault(tmp)
            spec(tmp, "machine_name: x;\na 'e' -> b;\n")
            self.assertIn("fsl.legacy_format", checks(tmp))

    def test_depends_on_and_cells_link_findings_to_questions(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_vault(tmp)
            page(tmp, "Q-006", "キャンセル")
            page(tmp, "Q-007", "二重送信", cells=["fsl/order:PendingPayment x submit"])
            spec(tmp, "// @depends_on: Q-006\n" + BASE % {"extra": "", "last": "pay"})
            F = run(tmp)[0]
            hole = [f for f in F if f["check"] == "fsl.state_event_hole"][0]
            self.assertEqual(hole["blocks"], ["Q-006", "Q-007"])


class NoToolTest(unittest.TestCase):
    def test_missing_fslc_is_one_finding(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_vault(tmp)
            spec(tmp, BASE % {"extra": "", "last": "pay"})
            spec(tmp, BASE % {"extra": "", "last": "pay"}, name="other.fsl")
            old = fsl.fslc_path
            fsl.fslc_path = lambda: None
            try:
                cs = checks(tmp)
            finally:
                fsl.fslc_path = old
            self.assertEqual(cs.count("fsl.tool_missing"), 1)

    def test_no_specs_no_findings(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_vault(tmp)
            self.assertEqual(run(tmp), ([], []))


if __name__ == "__main__":
    unittest.main()
