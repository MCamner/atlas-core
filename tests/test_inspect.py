from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest

from atlas_core.cli import main
from atlas_core.eventlog import EventLog, JsonlSink
from atlas_core.inspect_run import InspectError, inspect_run, render_inspection
from test_schemas import SchemaAssertions, load


class TestRunInspection(SchemaAssertions):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "events.jsonl"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _complete_log(self) -> None:
        log = EventLog("run-1", JsonlSink(self.path))
        log.append("run_started", max_iterations=2)
        log.append("plan_selected", iteration=1, route="repo_review", steps=["read"])
        log.append(
            "observation_recorded",
            iteration=1,
            added=[{"source_id": "README.md", "sha256": "a" * 64}],
            superseded=[],
            unchanged=[],
        )
        log.append(
            "decision_recorded",
            iteration=1,
            passed=False,
            unmet_criteria=["claims_are_settled"],
            evidence_gaps=["Need exact config lines"],
        )
        log.append(
            "run_stopped",
            iteration=1,
            stop_reason="insufficient_evidence",
            stop_class="bounded",
            status="stopped",
        )

    def test_machine_export_names_sources_uncertainties_and_stop_reason(self) -> None:
        self._complete_log()

        report = inspect_run(self.path, "run-1")

        self.assertEqual(report["schema"], "atlas-inspect.v1")
        self.assertEqual(report["route"], "repo_review")
        self.assertEqual(report["sources"], ["README.md"])
        self.assertEqual(report["stop_reason"], "insufficient_evidence")
        self.assertIn("Need exact config lines", report["uncertainties"])
        self.assertEqual(report["event_count"], 5)
        self.assertEqual(len(report["events"]), 5)
        self.assert_matches(load("atlas-inspect.v1.json"), report, "atlas-inspect.v1")

    def test_human_report_is_short_and_explicit(self) -> None:
        self._complete_log()

        text = render_inspection(inspect_run(self.path, "run-1"))

        self.assertIn("Run: run-1", text)
        self.assertIn("Sources: README.md", text)
        self.assertIn("Uncertainties: Need exact config lines", text)
        self.assertIn("Stopped: insufficient_evidence (bounded)", text)

    def test_unfinished_call_is_reported_as_uncertain_not_failed(self) -> None:
        log = EventLog("run-1", JsonlSink(self.path))
        log.append("run_started")
        call_id = log.start_call("tool_call", target="read_file", idempotent=True)

        report = inspect_run(self.path, "run-1")

        self.assertEqual(report["unfinished_calls"], [call_id])
        self.assertEqual(report["status"], "interrupted")
        self.assertTrue(any("outcome unknown" in item for item in report["uncertainties"]))

    def test_unknown_run_and_malformed_selected_run_fail_clearly(self) -> None:
        self._complete_log()
        with self.assertRaisesRegex(InspectError, "not found"):
            inspect_run(self.path, "missing")

        records = [json.loads(line) for line in self.path.read_text().splitlines()]
        records[1]["sequence"] = 99
        self.path.write_text(
            "".join(json.dumps(record) + "\n" for record in records),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(InspectError, "invalid event history"):
            inspect_run(self.path, "run-1")

    def test_cli_supports_json_export_and_clear_errors(self) -> None:
        self._complete_log()
        stdout = StringIO()
        with redirect_stdout(stdout):
            code = main([
                "inspect", "run-1", "--event-log", str(self.path), "--json"
            ])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout.getvalue())["run_id"], "run-1")

        stderr = StringIO()
        with redirect_stderr(stderr):
            code = main([
                "inspect", "missing", "--event-log", str(self.path), "--json"
            ])
        self.assertEqual(code, 1)
        self.assertIn("not found", stderr.getvalue())

    def test_cli_run_writes_a_log_that_inspect_can_export(self) -> None:
        stdout = StringIO()
        with redirect_stdout(stdout):
            run_code = main([
                "run", "answer this question", "--max-iterations", "1",
                "--event-log", str(self.path), "--json",
            ])
        run = json.loads(stdout.getvalue())

        exported = StringIO()
        with redirect_stdout(exported):
            inspect_code = main([
                "inspect", run["run_id"], "--event-log", str(self.path), "--json"
            ])

        self.assertIn(run_code, (0, 2, 3))
        self.assertEqual(inspect_code, 0)
        report = json.loads(exported.getvalue())
        self.assertEqual(report["run_id"], run["run_id"])
        self.assertEqual(report["stop_reason"], run["stop_reason"])
        self.assertEqual(report["iterations"], run["iteration"])


if __name__ == "__main__":
    unittest.main()
