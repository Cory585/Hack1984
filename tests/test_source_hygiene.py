"""Guards against invisible characters sneaking into source files (e.g. a backspace
where a regex '\\b' was meant, which silently breaks matching)."""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTROL = re.compile(rb"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class TestSourceHygiene(unittest.TestCase):
    def test_no_control_characters(self):
        bad = []
        for folder in ("conflict_check", "tests", "eval", "web"):
            for dirpath, _, files in os.walk(os.path.join(ROOT, folder)):
                for f in files:
                    if f.endswith((".py", ".html", ".json", ".txt")):
                        path = os.path.join(dirpath, f)
                        with open(path, "rb") as fh:
                            for n, line in enumerate(fh, 1):
                                if CONTROL.search(line):
                                    bad.append(f"{os.path.relpath(path, ROOT)}:{n}")
        self.assertEqual(bad, [], "control characters found")


if __name__ == "__main__":
    unittest.main()
