"""Offline contract and CLI regression tests."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/newsletter/validate_issue.py"
FIXTURE = ROOT / "newsletter/examples/synthetic-issue.json"
SPEC = importlib.util.spec_from_file_location("validate_issue", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class IssueTests(unittest.TestCase):
    def setUp(self):
        self.issue = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_fixture_valid_without_mutation(self):
        before = deepcopy(self.issue)
        self.assertEqual(MODULE.validate_issue(self.issue), [])
        self.assertEqual(self.issue, before)

    def test_both_locales_require_title_and_summary(self):
        for locale in ("zh-TW", "en"):
            for field in ("title", "summary"):
                for invalid in (None, "", " \t", 12, [], {}):
                    with self.subTest(locale=locale, field=field, invalid=invalid):
                        issue = deepcopy(self.issue)
                        issue["items"][0][locale][field] = invalid
                        self.assertTrue(MODULE.validate_issue(issue))

    def test_invalid_dates(self):
        for value in ("2025-02-29", "2026-13-01", "2026-04-31", "20261003", "2026-W40-6", "2026-1-01", "2026-10-03T00:00:00", None, 20261003):
            with self.subTest(value=value):
                self.issue["date"] = value
                self.assertTrue(MODULE.validate_issue(self.issue))

    def test_leap_date(self):
        self.issue["date"] = "2024-02-29"
        self.assertEqual(MODULE.validate_issue(self.issue), [])

    def test_urls_rejected(self):
        for value in (None, [], 1, "http://example.org/a", "javascript:alert(1)", "/relative", "https://", "https://user:pass@example.org/a", "https://example.org:bad/a", "https://example.org:99999/a", "https://exa mple.org/a", "https://example.org/\na", "https://example.org\\evil/a", "https://[broken/a"):
            with self.subTest(value=value):
                self.issue["items"][0]["source_url"] = value
                self.assertTrue(MODULE.validate_issue(self.issue))

    def test_duplicate_ids(self):
        self.issue["items"][1]["id"] = self.issue["items"][0]["id"]
        self.assertTrue(any("duplicate item" in e for e in MODULE.validate_issue(self.issue)))

    def test_duplicate_normalized_urls(self):
        self.issue["items"][0]["source_url"] = "https://EXAMPLE.org:443/news/1#first"
        self.issue["items"][1]["source_url"] = "https://example.org/news/1#second"
        self.assertTrue(any("duplicate source" in e for e in MODULE.validate_issue(self.issue)))

    def test_wrong_item_count(self):
        for count in (0, 9, 11):
            issue = deepcopy(self.issue)
            issue["items"] = (issue["items"] * 2)[:count]
            self.assertTrue(MODULE.validate_issue(issue))

    def test_wrong_shapes(self):
        for value in (None, [], "text", 1, True):
            self.assertTrue(MODULE.validate_issue(value))
        for value in (None, {}, "text", True):
            issue = deepcopy(self.issue)
            issue["items"] = value
            self.assertTrue(MODULE.validate_issue(issue))
        for value in (None, [], 1):
            issue = deepcopy(self.issue)
            issue["items"][0] = value
            self.assertTrue(MODULE.validate_issue(issue))

    def test_missing_fields(self):
        for key in ("schema_version", "date", "synthetic", "items"):
            issue = deepcopy(self.issue)
            del issue[key]
            self.assertTrue(MODULE.validate_issue(issue))
        for key in ("id", "source_url", "zh-TW", "en"):
            issue = deepcopy(self.issue)
            del issue["items"][0][key]
            self.assertTrue(MODULE.validate_issue(issue))

    def test_schema_version_bool_is_not_integer(self):
        self.issue["schema_version"] = True
        self.assertTrue(MODULE.validate_issue(self.issue))

    def test_cli_valid(self):
        result = subprocess.run([sys.executable, "-B", str(SCRIPT), str(FIXTURE)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("synthetic fixture", result.stdout)

    def test_cli_bad_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            for payload in (b"{", b"\xff", b'{"date":"2026-10-03","date":"2026-10-04"}', b"[]"):
                with self.subTest(payload=payload):
                    path.write_bytes(payload)
                    result = subprocess.run([sys.executable, "-B", str(SCRIPT), str(path)], capture_output=True, text=True)
                    self.assertEqual(result.returncode, 1)
                    self.assertIn("INVALID", result.stderr)
                    self.assertNotIn("Traceback", result.stderr)
            result = subprocess.run([sys.executable, "-B", str(SCRIPT), str(path.with_name("missing.json"))], capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)


if __name__ == "__main__":
    unittest.main()
