"""CI must fail closed and still retain normalized evidence for real failures."""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ci_summary as C


class CiSummaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.results = self.root / "results"
        self.run = self.results / "RUN-20261112-100000-EP-038-user"
        self.run.mkdir(parents=True)
        self.output = self.root / "artifacts"
        self.manifest = {
            "run_id": self.run.name, "status": "completed", "stop_reason": "completed",
            "started": "2026-11-12T10:00:00", "finished": "2026-11-12T10:00:30",
            "auth": {"status": "ok"}, "exit_code": 0, "interactions": 1,
            "execution_errors": [], "phases": {"coverage": "success", "stateful": "skip"},
        }
        self.evidence = {
            "run_id": self.run.name, "schema_version": 1, "execution_errors": [],
            "interactions": [{"id": "case-1", "error": None,
                "response": {"status": 200, "body": {"text": "PRIVATE RESPONSE BODY"}},
                "checks": [{"name": "not_a_server_error", "status": "success"}]}],
        }
        self.write_reports()
        (self.results / "last_run.txt").write_text(str(self.run), encoding="utf-8-sig")

    def write_reports(self):
        for name, data in (("run.json", self.manifest), ("evidence.json", self.evidence)):
            (self.run / name).write_text(json.dumps(data), encoding="utf-8")

    def summarize(self):
        with patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": ""}), contextlib.redirect_stdout(io.StringIO()):
            return C.main(["--results-dir", str(self.results), "--output-dir", str(self.output)])

    def assert_failed(self):
        self.assertEqual(self.summarize(), 1)
        self.assertIn("API smoke test: FAIL", (self.output / "summary.md").read_text())

    def test_success_stages_only_normalized_files_and_omits_bodies_from_summary(self):
        (self.run / "raw.html").write_text("secret raw report")
        (self.run / "auth_status.json").write_text("secret auth report")
        self.assertEqual(self.summarize(), 0)
        self.assertEqual({p.name for p in self.output.iterdir()}, {"run.json", "evidence.json", "summary.md"})
        summary = (self.output / "summary.md").read_text()
        self.assertIn("Successful checks | 1", summary)
        self.assertNotIn("PRIVATE RESPONSE BODY", summary)

    def test_failed_assertion_fails_even_when_exit_code_is_zero_and_preserves_evidence(self):
        self.evidence["interactions"][0]["checks"][0]["status"] = "failure"
        self.write_reports()
        self.assert_failed()
        self.assertTrue((self.output / "evidence.json").exists())

    def test_nonzero_exit_fails_even_when_checks_pass(self):
        self.manifest["exit_code"] = 1
        self.write_reports()
        self.assert_failed()

    def test_execution_errors_fail_without_exposing_error_messages(self):
        self.evidence["execution_errors"] = [{"message": "PRIVATE ERROR DETAIL"}]
        self.write_reports()
        self.assert_failed()
        self.assertNotIn("PRIVATE ERROR DETAIL", (self.output / "summary.md").read_text())

    def test_zero_requests_is_not_success(self):
        self.evidence["interactions"] = []
        self.manifest["interactions"] = 0
        self.write_reports()
        self.assert_failed()

    def test_missing_report_still_writes_failure_summary(self):
        (self.run / "evidence.json").unlink()
        self.assert_failed()
        self.assertTrue((self.output / "run.json").exists())

    def test_malformed_report_is_not_uploaded(self):
        (self.run / "evidence.json").write_text("PRIVATE INVALID JSON")
        self.assert_failed()
        self.assertFalse((self.output / "evidence.json").exists())
        self.assertNotIn("PRIVATE INVALID JSON", (self.output / "summary.md").read_text())

    def test_missing_pointer_fails(self):
        (self.results / "last_run.txt").unlink()
        self.assert_failed()

    def test_outside_pointer_is_rejected_without_copying_files(self):
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "evidence.json").write_text("private data")
        (self.results / "last_run.txt").write_text(str(outside))
        self.assert_failed()
        self.assertEqual({p.name for p in self.output.iterdir()}, {"summary.md"})

    def test_mismatched_run_id_fails_and_foreign_evidence_is_not_uploaded(self):
        self.evidence["run_id"] = "RUN-another-job"
        self.write_reports()
        self.assert_failed()
        self.assertFalse((self.output / "evidence.json").exists())

    def test_authentication_failure_fails_and_retains_diagnostics(self):
        self.manifest["auth"]["status"] = "failed"
        self.write_reports()
        self.assert_failed()
        self.assertTrue((self.output / "run.json").exists())

    def test_missing_completion_marker_fails(self):
        self.manifest["stop_reason"] = None
        self.write_reports()
        self.assert_failed()

    def test_missing_response_and_no_completed_checks_fail(self):
        self.evidence["interactions"][0]["response"] = None
        self.evidence["interactions"][0]["checks"] = []
        self.write_reports()
        self.assert_failed()

    def test_rate_limited_run_fails(self):
        self.evidence["interactions"][0]["response"]["status"] = 429
        self.write_reports()
        self.assert_failed()

    def test_step_summary_is_appended(self):
        target = self.root / "github-summary.md"
        target.write_text("Earlier step\n", encoding="utf-8")
        with patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(target)}), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(C.summarize(self.results, self.output), 0)
        text = target.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("Earlier step\n"))
        self.assertIn("API smoke test: PASS", text)


if __name__ == "__main__":
    unittest.main()
