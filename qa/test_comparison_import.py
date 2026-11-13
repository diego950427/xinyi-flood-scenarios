"""Upload boundary checks; never run SWMM or execute anything from the archive."""
from pathlib import Path
from io import BytesIO
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import comparison_import as c


def altered_zip(source, extras=None, omit=()):
    out = BytesIO()
    with zipfile.ZipFile(source) as src, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for n in src.namelist():
            if n not in omit and n not in (extras or {}):
                dst.writestr(n, src.read(n))
        for n, blob in (extras or {}).items():
            dst.writestr(n, blob)
    return out.getvalue()


class ComparisonImport(unittest.TestCase):
    source = ROOT / "examples/20261020_194910_441553a8/results.zip"

    def test_real_completed_result_is_importable_and_session_isolated(self):
        (ROOT / ".runtime").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / ".runtime") as tmp, patch.object(c, "STATE_ROOT", Path(tmp)):
            a = c.import_comparison_zip(self.source.read_bytes(), "a" * 40)
            b = c.import_comparison_zip(self.source.read_bytes(), "b" * 40)
            self.assertNotEqual(a, b)
            self.assertTrue((a / "grids.npz").exists())
            self.assertFalse((a / "result.qgs").exists())
            self.assertEqual(c.import_comparison_zip(self.source.read_bytes(), "a" * 40), a)

    def test_paths_cannot_escape(self):
        for n in ["../escape.txt", "C:/escape.txt"]:
            with self.subTest(n=n), self.assertRaises(ValueError):
                c._read_members(altered_zip(self.source, {n: b"bad"}))
        # Windows zipfile normalizes backslashes when writing; patch the stored
        # local/central names to actually test a backslash-bearing archive.
        bad = altered_zip(self.source, {"nested/escape.txt": b"bad"})
        with self.assertRaises(ValueError):
            c._read_members(bad.replace(b"nested/escape.txt", b"nested\\escape.txt"))

    def test_empty_or_missing_result_is_rejected(self):
        out = BytesIO()
        with zipfile.ZipFile(out, "w"):
            pass
        with self.assertRaises(ValueError):
            c._read_members(out.getvalue())
        with self.assertRaises(ValueError):
            c._read_members(altered_zip(self.source, omit=["grids.npz"]))

    def test_failed_results_are_not_completed(self):
        summary = {"passed": False, "checks": {"balance": False}}
        with self.assertRaises(ValueError):
            c._read_members(altered_zip(self.source, {"summary.json": json.dumps(summary)}))

    def test_embedded_code_is_not_imported(self):
        members = c._read_members(altered_zip(self.source, {"app.py": b"raise SystemExit(1)",
                               "index.html": b"<script>alert('x')</script>"}))
        self.assertNotIn("app.py", members)
        self.assertNotIn("index.html", members)

    def test_bad_zip_is_a_readable_error(self):
        with self.assertRaises(ValueError):
            c._read_members(b"not a zip")

    def test_low_disk_rejects_before_writing_results(self):
        from collections import namedtuple
        usage = namedtuple("Usage", "total used free")(1000_000_000, 900_000_000, 100_000_000)
        (ROOT / ".runtime").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / ".runtime") as tmp, patch.object(c, "STATE_ROOT", Path(tmp)):
            with patch.object(c.shutil, "disk_usage", return_value=usage), self.assertRaisesRegex(ValueError, "空間不足"):
                c.import_comparison_zip(self.source.read_bytes(), "a" * 40)
            self.assertFalse((Path(tmp) / "comparisons").exists())


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ComparisonImport))
    report = {"passed": result.wasSuccessful(), "run": result.testsRun,
              "failures": len(result.failures), "errors": len(result.errors),
              "scope": "ZIP boundaries and real example reloading; no solver rerun"}
    (ROOT / "qa/comparison_import_tests.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    raise SystemExit(0 if report["passed"] else 1)
