"""v1.4 box one: the host-facing run API — create, run, status, cancel, events.

A host such as Atlas One drives Core as a separate process. It needs a run id
before the run exists, a way to ask what a run is doing, a way to stop it, and
a stream of what it did. Every one of those reads the durable event log; none
of them is a second source of truth about a run.
"""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from atlas_core.budget import RunBudget, RunLimits
from atlas_core.cli import main
from atlas_core.controller import AtlasController
from atlas_core.eventlog import EventLog, JsonlSink, RunLock
from atlas_core.host_api import (
    EventLogInUse,
    RunIdInUse,
    cancel_path,
    cancel_requested,
    follow_events,
    lock_path,
    new_run_id,
    request_cancel,
    run_status,
    seal_lost_run,
    validate_run_id,
    writer_lock_path,
)
from atlas_core.inspect_run import inspect_run
from test_schemas import SchemaAssertions, load

TASK = "granska atlas-core och hitta nästa bästa förbättring"
LIMITS = RunLimits(wall_seconds=10, model_calls=0, tool_calls=8, tokens=0,
                   output_bytes=65536)


def _cli(*argv: str) -> tuple[int, str, str]:
    out, err = StringIO(), StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            code = main(list(argv))
        except SystemExit as exc:
            code = int(exc.code or 0)
    return code, out.getvalue(), err.getvalue()


class HostApiCase(SchemaAssertions):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.log = Path(self.tmp.name) / "events.jsonl"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _records(self, run_id: str) -> list[dict]:
        if not self.log.exists():
            return []
        return [
            record for record in map(json.loads, self.log.read_text().splitlines())
            if record["run_id"] == run_id
        ]


class TestRunIdentity(HostApiCase):
    def test_new_run_id_is_valid_and_unique(self) -> None:
        first, second = new_run_id(), new_run_id()
        self.assertEqual(validate_run_id(first), first)
        self.assertNotEqual(first, second)

    def test_unsafe_run_ids_are_refused(self) -> None:
        for bad in ("", " run", "../x", "a/b", "run\n", "x" * 129, "ä"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate_run_id(bad)

    def test_host_chosen_run_id_names_the_run_and_every_event(self) -> None:
        run = AtlasController(events=JsonlSink(self.log)).run(
            TASK, run_id="host-1", limits=LIMITS, json_mode=True,
        )
        self.assertEqual(run["run_id"], "host-1")
        records = self._records("host-1")
        self.assertTrue(records)
        self.assertEqual(len(records), len(self.log.read_text().splitlines()))

    def test_run_id_already_in_the_log_is_refused_without_writing(self) -> None:
        AtlasController(events=JsonlSink(self.log)).run(
            TASK, run_id="host-1", limits=LIMITS, json_mode=True,
        )
        before = self.log.read_bytes()
        with self.assertRaises(RunIdInUse):
            AtlasController(events=JsonlSink(self.log)).run(
                TASK, run_id="host-1", limits=LIMITS, json_mode=True,
            )
        self.assertEqual(self.log.read_bytes(), before)

    def test_run_id_held_by_a_live_run_is_refused(self) -> None:
        with RunLock(lock_path(self.log, "host-1")):
            with self.assertRaises(RunIdInUse):
                AtlasController(events=JsonlSink(self.log)).run(
                    TASK, run_id="host-1", limits=LIMITS, json_mode=True,
                )
        self.assertEqual(self._records("host-1"), [])

    def test_invalid_run_id_is_refused_before_anything_runs(self) -> None:
        with self.assertRaises(ValueError):
            AtlasController(events=JsonlSink(self.log)).run(
                TASK, run_id="../escape", limits=LIMITS, json_mode=True,
            )
        self.assertFalse(self.log.exists())


class TestStatus(HostApiCase):
    def test_unknown_run_is_not_found(self) -> None:
        status = run_status(self.log, "nobody")
        self.assertEqual(status["state"], "not_found")
        self.assertIsNone(status["stop_reason"])
        self.assert_matches(load("atlas-status.v1.json"), status, "status")

    def test_status_is_running_while_the_run_holds_its_lock(self) -> None:
        seen: list[dict] = []

        def reader(task: str, budget: RunBudget) -> list[str]:
            seen.append(run_status(self.log, "host-1"))
            return []

        AtlasController(events=JsonlSink(self.log)).run(
            TASK, run_id="host-1", limits=LIMITS, readers=[reader], json_mode=True,
        )
        self.assertEqual(seen[0]["state"], "running")
        self.assertIsNone(seen[0]["stop_reason"])

    def test_finished_run_reports_its_stop(self) -> None:
        run = AtlasController(events=JsonlSink(self.log)).run(
            TASK, run_id="host-1", limits=LIMITS, json_mode=True,
        )
        status = run_status(self.log, "host-1")
        self.assertEqual(status["state"], "finished")
        self.assertEqual(status["stop_reason"], run["stop_reason"])
        self.assertEqual(status["status"], run["status"])
        self.assertEqual(status["last_event_kind"], "run_stopped")
        self.assertEqual(status["event_count"], len(self._records("host-1")))
        self.assert_matches(load("atlas-status.v1.json"), status, "status")

    def test_started_run_without_stop_or_lock_is_interrupted(self) -> None:
        EventLog("host-1", JsonlSink(self.log)).append("run_started", max_iterations=2)
        self.assertEqual(run_status(self.log, "host-1")["state"], "interrupted")

    def test_contradictory_history_fails_closed(self) -> None:
        log = EventLog("host-1", JsonlSink(self.log))
        log.append("run_started", max_iterations=2)
        log.append("run_stopped", stop_reason="passed", stop_class="passed",
                   status="completed")
        log.append("plan_selected", iteration=1, route="repo_review", steps=[])
        code, _, err = _cli("status", "host-1", "--event-log", str(self.log))
        self.assertEqual(code, 1)
        self.assertIn("atlas status", err)


class TestCancel(HostApiCase):
    def test_cancel_before_start_stops_the_run_as_cancelled(self) -> None:
        run_id = new_run_id()
        code, out, _ = _cli("cancel", run_id, "--event-log", str(self.log), "--json")
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out)["cancel_requested"])
        code, out, _ = _cli("run", TASK, "--run-id", run_id,
                            "--event-log", str(self.log), "--json")
        self.assertEqual(code, 4)
        self.assertEqual(json.loads(out)["stop_reason"], "cancelled")
        self.assertEqual(run_status(self.log, run_id)["stop_reason"], "cancelled")

    def test_cancel_mid_run_is_honoured_at_the_next_boundary(self) -> None:
        def reader(task: str, budget: RunBudget) -> list[str]:
            request_cancel(self.log, "host-1")
            return []

        run = AtlasController(events=JsonlSink(self.log)).run(
            TASK, run_id="host-1", limits=LIMITS, readers=[reader],
            cancelled=cancel_requested(self.log, "host-1"), json_mode=True,
        )
        self.assertEqual(run["stop_reason"], "cancelled")
        self.assertTrue(run_status(self.log, "host-1")["cancel_requested"])

    def test_early_stop_in_the_reader_phase_is_logged_as_a_stop(self) -> None:
        # Regression: an exit before the first iteration returned without
        # `run_stopped`, so a run that failed cleanly read as a crash.
        def broken(task: str, budget: RunBudget) -> list[str]:
            raise OSError("disk gone")

        run = AtlasController(events=JsonlSink(self.log)).run(
            TASK, run_id="host-1", limits=LIMITS, readers=[broken], json_mode=True,
        )
        self.assertEqual(run["stop_reason"], "tool_error")
        status = run_status(self.log, "host-1")
        self.assertEqual((status["state"], status["stop_reason"]),
                         ("finished", "tool_error"))

    def test_cancel_of_a_finished_run_changes_nothing(self) -> None:
        AtlasController(events=JsonlSink(self.log)).run(
            TASK, run_id="host-1", limits=LIMITS, json_mode=True,
        )
        code, _, err = _cli("cancel", "host-1", "--event-log", str(self.log))
        self.assertEqual(code, 2)
        self.assertIn("already finished", err)
        self.assertFalse(cancel_path(self.log, "host-1").exists())

    def test_cancel_refuses_an_unsafe_run_id(self) -> None:
        code, _, _ = _cli("cancel", "../x", "--event-log", str(self.log))
        self.assertEqual(code, 1)
        self.assertEqual(list(Path(self.tmp.name).iterdir()), [])


class TestEvents(HostApiCase):
    def test_events_print_one_runs_records_as_jsonl(self) -> None:
        for run_id in ("host-1", "host-2"):
            AtlasController(events=JsonlSink(self.log)).run(
                TASK, run_id=run_id, limits=LIMITS, json_mode=True,
            )
        code, out, _ = _cli("events", "host-1", "--event-log", str(self.log))
        self.assertEqual(code, 0)
        lines = [json.loads(line) for line in out.splitlines()]
        self.assertEqual(lines, self._records("host-1"))
        self.assertTrue(all(line["schema"] == "atlas-event.v1" for line in lines))

    def test_follow_ends_at_run_stopped(self) -> None:
        AtlasController(events=JsonlSink(self.log)).run(
            TASK, run_id="host-1", limits=LIMITS, json_mode=True,
        )
        records = list(follow_events(self.log, "host-1", timeout=2.0))
        self.assertEqual(records[-1]["kind"], "run_stopped")
        self.assertEqual(records, self._records("host-1"))

    def test_follow_of_an_interrupted_run_ends_without_a_stop(self) -> None:
        EventLog("host-1", JsonlSink(self.log)).append("run_started", max_iterations=2)
        RunLock(lock_path(self.log, "host-1")).acquire().release()
        code, out, err = _cli("events", "host-1", "--event-log", str(self.log),
                              "--follow", "--timeout", "2")
        self.assertEqual(code, 2)
        self.assertEqual(len(out.splitlines()), 1)
        self.assertIn("interrupted", err)

    def test_follow_times_out_when_the_run_never_appears(self) -> None:
        code, out, err = _cli("events", "host-1", "--event-log", str(self.log),
                              "--follow", "--timeout", "0.3")
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("timed out", err)

    def test_events_of_an_unknown_run_without_follow_is_an_error(self) -> None:
        code, _, err = _cli("events", "nobody", "--event-log", str(self.log))
        self.assertEqual(code, 1)
        self.assertIn("not found", err)


class TestCliSurface(HostApiCase):
    def test_create_prints_a_fresh_valid_run_id(self) -> None:
        code, out, _ = _cli("create")
        self.assertEqual(code, 0)
        self.assertEqual(validate_run_id(out.strip()), out.strip())

    def test_run_id_requires_an_event_log(self) -> None:
        code, _, err = _cli("run", TASK, "--run-id", "host-1")
        self.assertEqual(code, 2)
        self.assertIn("--event-log", err)

    def test_status_json_matches_the_published_schema(self) -> None:
        _cli("run", TASK, "--run-id", "host-1", "--event-log", str(self.log))
        code, out, _ = _cli("status", "host-1", "--event-log", str(self.log), "--json")
        self.assertEqual(code, 0)
        self.assert_matches(load("atlas-status.v1.json"), json.loads(out), "status")


class TestOneWriterPerLog(HostApiCase):
    """v1.4 does not add shared-log concurrency. It refuses it."""

    def test_second_concurrent_writer_to_the_same_log_is_refused(self) -> None:
        with RunLock(writer_lock_path(self.log)):
            with self.assertRaises(EventLogInUse):
                AtlasController(events=JsonlSink(self.log)).run(
                    TASK, run_id="host-2", limits=LIMITS, json_mode=True,
                )
        self.assertFalse(self.log.exists())

    def test_cli_runs_one_run_per_event_log(self) -> None:
        code, _, _ = _cli("run", TASK, "--event-log", str(self.log))
        self.assertIn(code, (0, 2))
        before = self.log.read_bytes()
        code, _, err = _cli("run", TASK, "--run-id", "host-2",
                            "--event-log", str(self.log))
        self.assertEqual(code, 1)
        self.assertIn("one run per event log", err)
        self.assertEqual(self.log.read_bytes(), before)

    def test_python_api_may_still_serialize_runs_in_one_log(self) -> None:
        for run_id in ("host-1", "host-2"):
            AtlasController(events=JsonlSink(self.log)).run(
                TASK, run_id=run_id, limits=LIMITS, json_mode=True,
            )
        self.assertEqual(run_status(self.log, "host-2")["state"], "finished")


class TestSealLostRun(HostApiCase):
    """When the public CLI loses its worker, the log must end where the CLI
    result does — the event log is the audit source, not the parent's memory."""

    def _seal(self, reason: str = "budget_exhausted") -> str:
        return seal_lost_run(
            self.log, "host-1", stop_reason=reason, detail="wall_seconds",
            task=TASK, max_iterations=2,
        )

    def test_partial_history_gets_the_parents_stop(self) -> None:
        log = EventLog("host-1", JsonlSink(self.log))
        log.append("run_started", max_iterations=2)
        log.append("plan_selected", iteration=1, route="repo_review", steps=[])
        self.assertEqual(self._seal(), "budget_exhausted")
        status = run_status(self.log, "host-1")
        self.assertEqual((status["state"], status["stop_reason"]),
                         ("finished", "budget_exhausted"))
        self.assertEqual(inspect_run(self.log, "host-1")["iterations"], 1)

    def test_worker_killed_before_writing_anything(self) -> None:
        self.assertEqual(self._seal(), "budget_exhausted")
        kinds = [record["kind"] for record in self._records("host-1")]
        self.assertEqual(kinds, ["run_started", "run_stopped"])
        self.assertEqual(run_status(self.log, "host-1")["state"], "finished")

    def test_a_stop_the_worker_already_logged_wins(self) -> None:
        log = EventLog("host-1", JsonlSink(self.log))
        log.append("run_started", max_iterations=2)
        log.append("run_stopped", stop_reason="insufficient_evidence",
                   stop_class="bounded", status="stopped")
        before = self.log.read_bytes()
        self.assertEqual(self._seal(), "insufficient_evidence")
        self.assertEqual(self.log.read_bytes(), before)

    def test_torn_tail_from_the_killed_worker_is_dropped_then_sealed(self) -> None:
        EventLog("host-1", JsonlSink(self.log)).append("run_started", max_iterations=2)
        with self.log.open("a", encoding="utf-8") as handle:
            handle.write('{"schema": "atlas-event.v1", "run_')
        self.assertEqual(self._seal("cancelled"), "cancelled")
        self.assertEqual(run_status(self.log, "host-1")["stop_reason"], "cancelled")


@unittest.skipUnless(os.name == "posix", "POSIX process-group guard")
class TestPublicCliProcess(HostApiCase):
    """The public entrypoint runs the loop in a guarded worker; the run id and
    the cancel request must survive that hop."""

    def test_cancelled_run_through_the_hard_cli_exits_4(self) -> None:
        run_id = new_run_id()
        request_cancel(self.log, run_id)
        result = subprocess.run(
            [sys.executable, "-m", "atlas_core.cli", "run", TASK,
             "--run-id", run_id, "--event-log", str(self.log), "--json"],
            capture_output=True, timeout=60,
        )
        self.assertEqual(result.returncode, 4, result.stderr)
        run = json.loads(result.stdout)
        self.assertEqual((run["run_id"], run["stop_reason"]), (run_id, "cancelled"))
        self.assertEqual(run_status(self.log, run_id)["state"], "finished")

    def _public_run(self, *extra: str) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            [sys.executable, "-m", "atlas_core.cli", "run", TASK,
             "--event-log", str(self.log), "--json", *extra],
            capture_output=True, timeout=60,
        )

    def test_hard_deadline_leaves_the_same_terminal_state_in_the_log(self) -> None:
        # No --run-id: the parent must still know which run to seal.
        result = self._public_run("--wall-seconds", "0.05")
        run = json.loads(result.stdout)
        self.assertEqual(run["stop_reason"], "budget_exhausted", result.stderr)
        self.assertEqual(result.returncode, 2)
        status = run_status(self.log, run["run_id"])
        self.assertEqual((status["state"], status["stop_reason"]),
                         ("finished", "budget_exhausted"))

    def test_public_cli_refuses_a_log_that_already_holds_a_run(self) -> None:
        self.assertIn(self._public_run().returncode, (0, 2))
        before = self.log.read_bytes()
        result = self._public_run()
        self.assertEqual(result.returncode, 1)
        self.assertIn(b"one run per event log", result.stderr)
        self.assertEqual(self.log.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
