# -*- coding: utf-8 -*-
import unittest

import helpers  # noqa: F401  (sys.path)
from reqmap import fsl

SPEC = '''// @area: A-04
// @depends_on: Q-006, Q-007
// @events: refund
// @critical: cancel
// @impossible: Draft x pay   // 未送信に決済は無い
requirements OrderStatus {
  process Order {
    stages Draft, Paid, Cancelled
    initial Draft
    transition pay Draft -> Paid by Customer covers REQ-1 "支払"
    @reqmap.event("cancel")
    @undecided("Q-006 返金条件が未定")
    transition cancel_paid Paid -> Cancelled by Customer covers REQ-2 "支払後取消"
  }
  forbidden FB-1 "二重決済" {
    pay(0) pay(0)
    expect rejected
  }
  init "undecided: 初期状態は運用開始時に決める" { }
}
'''


class SourceTest(unittest.TestCase):
    def test_directives(self):
        s = fsl.read_source(SPEC)
        self.assertFalse(s["legacy"])
        self.assertEqual(s["area"], "A-04")
        self.assertEqual(s["depends_on"], ["Q-006", "Q-007"])
        self.assertEqual(s["extra_events"], ["refund"])
        self.assertEqual(s["critical"], ["cancel"])
        self.assertEqual(s["impossible"], {("draft", "pay")})

    def test_annotations_attach_to_next_transition(self):
        s = fsl.read_source(SPEC)
        self.assertEqual(s["events"], {"cancel_paid": "cancel"})
        self.assertEqual(s["undecided"][0]["decl"], "transition cancel_paid")
        self.assertEqual(s["undecided"][0]["reason"], "Q-006 返金条件が未定")

    def test_string_slot_undecided(self):
        s = fsl.read_source(SPEC)
        self.assertEqual(s["undecided"][1]["decl"], "init")
        self.assertEqual(s["undecided"][1]["reason"], "初期状態は運用開始時に決める")

    def test_forbidden_last_step(self):
        s = fsl.read_source(SPEC)
        self.assertEqual(s["forbidden"][0]["id"], "FB-1")
        self.assertEqual(s["forbidden"][0]["steps"], [("pay", "0")])
        self.assertEqual(s["forbidden"][0]["last"], ("pay", "0"))

    def test_acceptance_ids_are_read(self):
        s = fsl.read_source(SPEC + '\nacceptance AC-1 "正常系" {\n  pay(0)\n  expect Order 0 in Paid\n}\n')
        self.assertEqual(s["acceptance"], ["AC-1"])
        self.assertEqual(fsl.read_source(SPEC)["acceptance"], [])

    def test_legacy_jssm_is_detected(self):
        self.assertTrue(fsl.read_source("machine_name: x;\na 'e' -> b;\n")["legacy"])


if __name__ == "__main__":
    unittest.main()
