# -*- coding: utf-8 -*-
import tempfile
import unittest

from helpers import make_vault, page
from reqmap import graph, model


class BackCalcTest(unittest.TestCase):
    def test_upstream_deadline_uses_downstream_response_days(self):
        # a（自社・0日）が b（クライアント・14日）を止める。期限 10-31。
        # b は 10-17 に出す必要がある → a はそれまでに決まっていなければならない。
        with tempfile.TemporaryDirectory() as tmp:
            make_vault(tmp)
            page(tmp, "a", "A", owner="自社")
            page(tmp, "b", "B", owner="クライアント", prereqs=["a"])
            r = graph.analyse(model.Project(tmp))["result"]
            self.assertEqual(r["b"]["ask_by"], "2026-10-17")
            self.assertEqual(r["a"]["need_by"], "2026-10-17")
            self.assertEqual(r["a"]["ask_by"], "2026-10-17")


class CycleTest(unittest.TestCase):
    def test_cycle_only_affects_its_own_nodes(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_vault(tmp)
            page(tmp, "x", "X", prereqs=["y"])
            page(tmp, "y", "Y", prereqs=["x"])
            page(tmp, "up", "UP", owner="クライアント")
            page(tmp, "down", "DOWN", owner="クライアント", prereqs=["up"])
            an = graph.analyse(model.Project(tmp))
            self.assertEqual(an["cycle_nodes"], ["x", "y"])
            r = an["result"]
            self.assertEqual(r["down"]["depth"], 1)
            self.assertEqual(r["up"]["need_by"], "2026-10-17")

    def test_scc_finds_node_reachable_only_via_cross_edge(self):
        # r→x, x→r, r→y, y→x: y は循環上にあるが DFS の back-edge 経路には出ない
        edges = {"r": [("x", "blocks"), ("y", "blocks")], "x": [("r", "blocks")],
                 "y": [("x", "blocks")]}
        self.assertEqual(graph.scc_cycle_nodes(edges), {"r", "x", "y"})


class DerivedTest(unittest.TestCase):
    def test_derived_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_vault(tmp)
            page(tmp, "c", "C", status="decided", decision="Xにする。")
            page(tmp, "d", "D", derives=["c"])
            page(tmp, "e", "E")
            r = graph.analyse(model.Project(tmp))["result"]
            self.assertTrue(r["d"]["derived"])
            self.assertTrue(r["d"]["ready"])
            self.assertFalse(r["e"]["derived"])


if __name__ == "__main__":
    unittest.main()
