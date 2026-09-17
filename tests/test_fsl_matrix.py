# -*- coding: utf-8 -*-
import unittest

import helpers  # noqa: F401
from reqmap import fsl


def idx(name):
    return {"kind": "index", "collection": {"kind": "var", "name": name},
            "index": {"kind": "var", "name": "c"}}


def eq(name, member):
    return {"kind": "binary", "operator": "==", "left": idx(name),
            "right": {"kind": "var", "name": member}}


def act(name, frm, to):
    return {"name": name, "requires": [eq("order_stage", frm)],
            "updates": [{"kind": "assign",
                         "target": {"kind": "index", "name": "order_stage",
                                    "index": {"kind": "var", "name": "c"}},
                         "value": {"kind": "var", "name": to}}]}


KERNEL = {
    "types": [{"name": "OrderStage",
               "definition": {"kind": "enum", "members": ["Draft", "Pending", "Paid", "Cancelled"]}},
              {"name": "Order", "definition": {"kind": "domain", "lo": 0, "hi": 1}}],
    "state": [{"name": "order_stage",
               "type": {"kind": "map", "key": {"kind": "named", "name": "Order"},
                        "value": {"kind": "named", "name": "OrderStage"}}}],
    "init": {"statements": [{"kind": "forall", "statements": [
        {"kind": "assign", "target": {"kind": "index", "name": "order_stage",
                                      "index": {"kind": "var", "name": "c"}},
         "value": {"kind": "var", "name": "Draft"}}]}]},
    "actions": [act("submit", "Draft", "Pending"), act("pay", "Pending", "Paid"),
                act("cancel", "Pending", "Cancelled"), act("cancel_paid", "Paid", "Cancelled")],
}


def holes(F):
    return {(f["target"]["state"], f["target"]["event"])
            for f in F if f["check"] == "fsl.state_event_hole"}


class ProcessTest(unittest.TestCase):
    def test_process_extraction(self):
        p = fsl.processes(KERNEL)[0]
        self.assertEqual(p["map"], "order_stage")
        self.assertEqual(p["stages"], ["Draft", "Pending", "Paid", "Cancelled"])
        self.assertEqual(p["initial"], "Draft")
        self.assertIn(("pay", "Pending", "Paid"), p["trans"])
        self.assertEqual(len(p["trans"]), 4)

    def test_or_guard_yields_two_sources(self):
        k = dict(KERNEL)
        a = act("cancel", "Pending", "Cancelled")
        a["requires"] = [{"kind": "binary", "operator": "or",
                          "left": eq("order_stage", "Pending"), "right": eq("order_stage", "Paid")}]
        k = dict(KERNEL, actions=[act("submit", "Draft", "Pending"), a])
        p = fsl.processes(k)[0]
        self.assertIn(("cancel", "Pending", "Cancelled"), p["trans"])
        self.assertIn(("cancel", "Paid", "Cancelled"), p["trans"])


class MatrixTest(unittest.TestCase):
    def _run(self, **src):
        s = dict(fsl.read_source(""), **src)
        return fsl.matrix_findings(s, fsl.processes(KERNEL)[0], "fsl/order", "medium", [])

    def test_adjacent_holes_and_event_grouping(self):
        F, summ = self._run(events={"cancel_paid": "cancel"})
        cells = holes(F)
        self.assertIn(("Paid", "pay"), cells)          # 二重決済
        self.assertIn(("Pending", "submit"), cells)    # 二重送信
        self.assertNotIn(("Paid", "cancel"), cells)    # cancel_paid が cancel として定義済み
        self.assertIn(("Draft", "cancel"), cells)      # Pending の隣なので問う
        self.assertNotIn(("Cancelled", "pay"), cells)  # 終端（出る遷移が無い）は問わない
        self.assertEqual(summ["events"], 3)
        self.assertEqual(summ["stages"], 4)

    def test_hole_question_states_the_current_behaviour(self):
        F, _ = self._run()
        q = [f["question"] for f in F if f["check"] == "fsl.state_event_hole"][0]
        self.assertIn("いまの仕様では拒否", q)
        self.assertIn("forbidden", q)

    def test_critical_event_is_asked_everywhere(self):
        F, _ = self._run(critical=["pay"])
        self.assertIn(("Draft", "pay"), holes(F))

    def test_impossible_directive_suppresses_a_cell(self):
        F, _ = self._run(impossible={("draft", "cancel")})
        self.assertNotIn(("Draft", "cancel"), holes(F))

    def test_forbidden_covers_a_cell(self):
        F, _ = self._run(forbidden=[{"id": "FB-1", "steps": [("submit", "0"), ("pay", "0")],
                                     "last": ("pay", "0")}])
        self.assertNotIn(("Paid", "pay"), holes(F))

    def test_summary_carries_the_full_matrix(self):
        F, summ = self._run(events={"cancel_paid": "cancel"}, impossible={("draft", "cancel")},
                            forbidden=[{"id": "FB-1", "steps": [("submit", "0"), ("pay", "0")],
                                        "last": ("pay", "0")}])
        cell = {(r["stage"], c["e"]): c["s"] for r in summ["matrix"]["rows"] for c in r["cells"]}
        self.assertEqual(cell[("Draft", "submit")], "defined")
        self.assertEqual(cell[("Pending", "submit")], "hole")
        self.assertEqual(cell[("Paid", "pay")], "forbidden")
        self.assertEqual(cell[("Draft", "cancel")], "impossible")
        self.assertEqual(cell[("Cancelled", "pay")], "terminal")
        self.assertEqual(cell[("Draft", "pay")], "hole")          # Draft は Pending の隣なので問う
        self.assertEqual(cell[("Paid", "submit")], "suppressed")  # Paid は Draft の隣ではない
        self.assertEqual(summ["matrix"]["events"], ["submit", "pay", "cancel"])

    def test_claimed_cell_is_linked_in_the_matrix(self):
        s = dict(fsl.read_source(""))
        F, summ = fsl.matrix_findings(s, fsl.processes(KERNEL)[0], "fsl/order", "medium", [],
                                      claimed={"fsl/order:Paid x pay"})
        cell = {(r["stage"], c["e"]): c["s"] for r in summ["matrix"]["rows"] for c in r["cells"]}
        self.assertEqual(cell[("Paid", "pay")], "linked")
        self.assertNotIn(("Paid", "pay"), holes(F))

    def test_unused_event_and_unreachable_stage(self):
        k = dict(KERNEL, actions=KERNEL["actions"][:2])  # Cancelled に入る遷移が無い
        s = dict(fsl.read_source(""), extra_events=["refund"])
        F, _ = fsl.matrix_findings(s, fsl.processes(k)[0], "fsl/order", "medium", [])
        cs = [f["check"] for f in F]
        self.assertIn("fsl.unused_event", cs)
        self.assertIn("fsl.unreachable_stage", cs)


if __name__ == "__main__":
    unittest.main()
