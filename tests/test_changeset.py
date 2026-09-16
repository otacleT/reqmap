# -*- coding: utf-8 -*-
import os
import tempfile
import unittest

from helpers import make_vault
from reqmap import changeset, model

SRC = ("田中様: 決まっていません。\n"
       "佐藤様: 次回までに整理してお送りします。\n"
       "田中様: 次回までに整理してお送りします。\n"
       "大石: 商品画像のアップロードでネットワークが切れた場合の挙動が決まっていません。\n")


def _proj(tmp):
    make_vault(tmp)
    os.makedirs(os.path.join(tmp, "sources"))
    with open(os.path.join(tmp, "sources", "m.md"), "w", encoding="utf-8") as f:
        f.write(SRC)
    return model.Project(tmp)


def _chg(quote):
    return {"op": "create", "id": "x", "title": "X", "quote": quote}


class QuoteGateTest(unittest.TestCase):
    def test_short_quote_is_raised_to_human(self):
        with tempfile.TemporaryDirectory() as tmp:
            g, why = changeset.classify(_chg("決まっていません。"), _proj(tmp), SRC)
            self.assertEqual(g, changeset.HUMAN)
            self.assertTrue(any("短" in w for w in why), why)

    def test_ambiguous_quote_is_raised_to_human(self):
        with tempfile.TemporaryDirectory() as tmp:
            g, why = changeset.classify(_chg("次回までに整理してお送りします。"), _proj(tmp), SRC)
            self.assertEqual(g, changeset.HUMAN)
            self.assertTrue(any("複数回" in w for w in why), why)

    def test_specific_quote_stays_auto(self):
        with tempfile.TemporaryDirectory() as tmp:
            g, _ = changeset.classify(
                _chg("商品画像のアップロードでネットワークが切れた場合の挙動が決まっていません。"),
                _proj(tmp), SRC)
            self.assertEqual(g, changeset.AUTO)

    def test_missing_quote_is_still_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            g, _ = changeset.classify(_chg("原文に無い一文です。"), _proj(tmp), SRC)
            self.assertEqual(g, changeset.BLOCKED)


if __name__ == "__main__":
    unittest.main()
