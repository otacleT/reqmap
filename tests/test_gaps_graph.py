# -*- coding: utf-8 -*-
import tempfile
import unittest

from helpers import make_vault, page
from reqmap import gaps, model


def checks(root):
    return [f["check"] for f in gaps.run(model.Project(root))["findings"]]


class ConflictTest(unittest.TestCase):
    def test_both_decided_is_a_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_vault(tmp)
            page(tmp, "c", "C", status="decided", decision="Xにする。")
            page(tmp, "e", "E", status="decided", decision="Yにする。", conflicts=["c"])
            self.assertIn("graph.conflict", checks(tmp))

    def test_one_decided_marks_the_other_as_drop_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_vault(tmp)
            page(tmp, "c", "C", status="decided", decision="Xにする。")
            page(tmp, "e", "E", conflicts=["c"])
            cs = checks(tmp)
            self.assertIn("graph.conflict_pending", cs)
            self.assertNotIn("graph.conflict", cs)

    def test_both_open_is_silent(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_vault(tmp)
            page(tmp, "c", "C")
            page(tmp, "e", "E", conflicts=["c"])
            cs = checks(tmp)
            self.assertNotIn("graph.conflict", cs)
            self.assertNotIn("graph.conflict_pending", cs)

    def test_mutual_declaration_is_reported_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_vault(tmp)
            page(tmp, "c", "C", status="decided", decision="X。", conflicts=["e"])
            page(tmp, "e", "E", status="decided", decision="Y。", conflicts=["c"])
            self.assertEqual(checks(tmp).count("graph.conflict"), 1)


if __name__ == "__main__":
    unittest.main()
