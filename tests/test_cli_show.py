# -*- coding: utf-8 -*-
import subprocess
import tempfile
import unittest

from helpers import CLI, make_vault, page


def show(root, ref):
    r = subprocess.run([CLI, "show", ref, "--root=%s" % root], capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


class ShowTest(unittest.TestCase):
    def test_show_lists_everything_about_one_question(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_vault(tmp)
            page(tmp, "up", "上流の論点", status="decided", decision="Xにする。")
            page(tmp, "q", "真ん中の論点", prereqs=["up"], owner="クライアント",
                 cells=["lifecycle:user x retain"], log=["2026-09-01 asked | 定例で依頼"],
                 constrains=["up"])
            page(tmp, "down", "下流の論点", prereqs=["q"])
            code, out = show(tmp, "q")
            self.assertEqual(code, 0, out)
            for s in ("真ん中の論点", "■ 前提", "up", "■ 下流", "down", "■ 日付",
                      "■ やりとり", "2026-09-01", "lifecycle:user x retain", "■ 観点"):
                self.assertIn(s, out)

    def test_show_resolves_title_and_reports_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_vault(tmp)
            page(tmp, "q", "題名で引ける論点")
            code, out = show(tmp, "題名で引ける論点")
            self.assertEqual(code, 0, out)
            self.assertIn("q", out)
            code, out = show(tmp, "nope")
            self.assertEqual(code, 1)
            self.assertIn("見つかりません", out)


if __name__ == "__main__":
    unittest.main()
