# -*- coding: utf-8 -*-
import json
import subprocess
import tempfile
import unittest

from helpers import CLI, make_vault, page


class JsonTest(unittest.TestCase):
    def test_json_serialises_log_dates(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_vault(tmp)
            page(tmp, "a", "A", log=["2026-09-01 asked | 定例"])
            r = subprocess.run([CLI, "json", "--stdout", "--root=%s" % tmp],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr[-300:])
            d = json.loads(r.stdout)
            self.assertEqual(d["items"]["a"]["log"][0]["date"], "2026-09-01")


if __name__ == "__main__":
    unittest.main()
