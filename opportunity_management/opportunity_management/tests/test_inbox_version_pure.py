"""Bench-free tests for inbox_version.read_current (python3 tests/test_inbox_version_pure.py)."""

import importlib.util
import os
import sys
import tempfile
import types
import unittest

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load():
    fake = types.ModuleType("frappe")
    fake.whitelist = lambda **kw: (lambda f: f)
    fake.local = types.SimpleNamespace(response=types.SimpleNamespace(headers={}))
    sys.modules.setdefault("frappe", fake)
    spec = importlib.util.spec_from_file_location("inbox_version_under_test", os.path.join(_HERE, "inbox_version.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


V = _load()


class TestReadCurrent(unittest.TestCase):
    def _file(self, text):
        fd, path = tempfile.mkstemp()
        with os.fdopen(fd, "w") as fh:
            fh.write(text)
        self.addCleanup(os.remove, path)
        return path

    def test_version(self):
        self.assertEqual(V.read_current(self._file("202611191857-407ce08\n")), "202611191857-407ce08")

    def test_missing_or_unsafe(self):
        self.assertEqual(V.read_current("/nonexistent/CURRENT"), "")
        for bad in ("", "a/b", "..", "../x", ".hidden"):
            self.assertEqual(V.read_current(self._file(bad)), "", bad)


if __name__ == "__main__":
    unittest.main()
