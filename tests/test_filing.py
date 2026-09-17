# -*- coding: utf-8 -*-
import os
import shutil
import subprocess
import tempfile
import unittest

from helpers import CLI, make_vault, page
from reqmap import gaps, model

GRID = '''id: lifecycle
title: データのライフサイクル
area: A-02
rows:
  - media | 画像 | 画像
  - log | ログ | ログ
cols:
  - store | 保存先 | 保存
  - retain | 保持期間 | 保持期間
skip: []
'''
SPEC = '''// @area: A-01
requirements OrderStatus {
  process Order {
    stages Draft, Paid, Cancelled
    initial Draft
    transition pay Draft -> Paid by Customer covers REQ-O-001 "支払"
    transition cancel Draft -> Cancelled by Customer covers REQ-O-002 "取消"
    @undecided("返金するかは未定")
    transition refund Paid -> Cancelled by Shop covers REQ-O-003 "返金"
  }
  forbidden FB-O-001 "二重決済" {
    pay(0) pay(0)
    expect rejected
  }
  terminal { forall c: Order { stage(c) == Paid or stage(c) == Cancelled } }
}
verify { instances Order = 2 }
'''


def grid(root):
    with open(os.path.join(root, "models", "grids", "lifecycle.yml"), "w", encoding="utf-8") as f:
        f.write(GRID)


def spec(root):
    with open(os.path.join(root, "models", "fsl", "order.fsl"), "w", encoding="utf-8") as f:
        f.write(SPEC)


def finding(root, check, **match):
    for f in gaps.run(model.Project(root))["findings"]:
        if f["check"] == check and all(f["target"].get(k) == v for k, v in match.items()):
            return f
    return None


def file_(root, *ids):
    r = subprocess.run([CLI, "gaps", "--file=%s" % ",".join(ids), "--root=%s" % root],
                       capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


class GridFilingTest(unittest.TestCase):
    def test_grid_empty_becomes_a_linked_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_vault(tmp)
            grid(tmp)
            page(tmp, "x", "画像の保持期間", area="A-02", cells=["lifecycle:media x retain"])
            f = finding(tmp, "grid.empty", row="media", col="store")
            self.assertIsNotNone(f)
            code, out = file_(tmp, f["id"])
            self.assertEqual(code, 0, out)
            path = os.path.join(tmp, "questions", "A-02", "lifecycle.media-store.md")
            self.assertTrue(os.path.exists(path), out)
            text = open(path, encoding="utf-8").read()
            self.assertIn("lifecycle:media x store", text)
            self.assertIn("status: open", text)
            self.assertIn(f["id"], text)          # 出どころ
            self.assertIsNone(finding(tmp, "grid.empty", row="media", col="store"))

    def test_row_empty_links_the_whole_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_vault(tmp)
            grid(tmp)
            page(tmp, "x", "画像の保持期間", area="A-02", cells=["lifecycle:media x retain"])
            f = finding(tmp, "grid.row_empty", row="log")
            code, out = file_(tmp, f["id"])
            self.assertEqual(code, 0, out)
            text = open(os.path.join(tmp, "questions", "A-02", "lifecycle.log.md"), encoding="utf-8").read()
            self.assertIn("lifecycle:log x store", text)
            self.assertIn("lifecycle:log x retain", text)
            self.assertIsNone(finding(tmp, "grid.row_empty", row="log"))

    def test_dropped_page_does_not_claim_cells(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_vault(tmp)
            grid(tmp)
            page(tmp, "y", "ログの保存先", area="A-02", cells=["lifecycle:log x store"])
            page(tmp, "x", "画像の保持期間", area="A-02", status="dropped",
                 cells=["lifecycle:media x retain"])
            # 取下げページの紐付けは無効なので、media 行は丸ごと空に戻る
            self.assertIsNotNone(finding(tmp, "grid.row_empty", row="media"))

    def test_refuses_findings_that_are_not_questions(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_vault(tmp)
            page(tmp, "a", "A")
            f = finding(tmp, "graph.isolated")
            code, out = file_(tmp, f["id"])
            self.assertEqual(code, 1, out)
            self.assertIn("論点ではありません", out)
            self.assertEqual(len(os.listdir(os.path.join(tmp, "questions", "A-01"))), 1)

    def test_refuses_unknown_and_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_vault(tmp)
            grid(tmp)
            page(tmp, "x", "画像の保持期間", area="A-02", cells=["lifecycle:media x retain"])
            code, out = file_(tmp, "f-0000000000")
            self.assertEqual(code, 1)
            self.assertIn("見つかりません", out)
            page(tmp, "lifecycle.log", "手で作った同じID", area="A-01")   # 同じ ID が別領域にある
            f = finding(tmp, "grid.row_empty", row="log")
            code, out = file_(tmp, f["id"])
            self.assertEqual(code, 1, out)
            self.assertIn("すでに", out)
            self.assertFalse(os.path.exists(os.path.join(tmp, "questions", "A-02", "lifecycle.log.md")))


@unittest.skipIf(shutil.which("fslc") is None, "fslc がありません")
class FslFilingTest(unittest.TestCase):
    def test_hole_becomes_a_linked_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_vault(tmp)
            spec(tmp)
            f = finding(tmp, "fsl.state_event_hole", state="Paid", event="cancel")
            self.assertIsNotNone(f)
            code, out = file_(tmp, f["id"])
            self.assertEqual(code, 0, out)
            path = os.path.join(tmp, "questions", "A-01", "order.paid-cancel.md")
            text = open(path, encoding="utf-8").read()
            self.assertIn("fsl/order:Paid x cancel", text)
            self.assertIsNone(finding(tmp, "fsl.state_event_hole", state="Paid", event="cancel"))

    def test_undecided_unlinked_prints_the_id_to_write_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_vault(tmp)
            spec(tmp)
            f = finding(tmp, "fsl.undecided_unlinked")
            code, out = file_(tmp, f["id"])
            self.assertEqual(code, 0, out)
            self.assertIn('@undecided("order.refund', out)
            text = open(os.path.join(tmp, "questions", "A-01", "order.refund.md"), encoding="utf-8").read()
            self.assertIn("返金するかは未定", text)


if __name__ == "__main__":
    unittest.main()
