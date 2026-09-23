from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any, cast

from atlas_core import AtlasController, JsonlSink, StubModelAdapter
from atlas_core.eventlog import EventLog, ResumeRefused, RunLock, read_jsonl


ANSWER = (
    "# Svar\n\n" + "Ett deterministiskt svar. " * 12
    + "\n\n## Recommendation\nX.\n\n## Next step\nY.\n\n## Confidence\nHög.\n"
)


class TestSafeResume(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "events.jsonl"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _interrupted(self, *, idempotent: bool = True) -> str:
        log = EventLog("run-1", JsonlSink(self.path))
        log.append(
            "run_started",
            task_sha256="2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824",
            max_iterations=1,
            observations_sha256="4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
            snapshot_id=None,
            evidence_sha256=None,
        )
        log.start_call("observe", target="repo", idempotent=idempotent)
        return log.run_id

    def test_resume_appends_interrupted_and_resumed_to_the_same_run(self) -> None:
        self._interrupted()
        controller = AtlasController(
            max_iterations=1,
            model_adapter=StubModelAdapter(ANSWER),
            events=JsonlSink(self.path),
        )

        run = controller.resume("hello", run_id="run-1", json_mode=True)
        self.assertIsInstance(run, dict)

        records = read_jsonl(self.path)
        self.assertEqual(run["run_id"], "run-1")  # type: ignore[index]
        self.assertEqual({record["run_id"] for record in records}, {"run-1"})
        kinds = [record["kind"] for record in records]
        self.assertIn("interrupted", kinds)
        self.assertIn("resumed", kinds)
        self.assertEqual([record["sequence"] for record in records], list(range(len(records))))

        fresh = AtlasController(
            max_iterations=1, model_adapter=StubModelAdapter(ANSWER)
        ).run("hello", json_mode=True)
        self.assertIsInstance(fresh, dict)
        self.assertEqual(run["status"], fresh["status"])  # type: ignore[index]
        self.assertEqual(run["stop_reason"], fresh["stop_reason"])  # type: ignore[index]

    def test_resume_selects_one_run_from_a_shared_log(self) -> None:
        other = EventLog("other-run", JsonlSink(self.path))
        other.append(
            "run_started",
            task_sha256="x" * 64,
            max_iterations=1,
            observations_sha256="y" * 64,
            snapshot_id=None,
            evidence_sha256=None,
        )
        self._interrupted()
        controller = AtlasController(max_iterations=1, events=JsonlSink(self.path))

        run = controller.resume("hello", run_id="run-1", json_mode=True)

        self.assertIsInstance(run, dict)
        self.assertEqual(run["run_id"], "run-1")  # type: ignore[index]
        other_records = [
            record for record in read_jsonl(self.path)
            if record["run_id"] == "other-run"
        ]
        self.assertEqual([record["kind"] for record in other_records], ["run_started"])

    def test_resume_refuses_a_different_task(self) -> None:
        self._interrupted()
        controller = AtlasController(max_iterations=1, events=JsonlSink(self.path))

        with self.assertRaisesRegex(ResumeRefused, "task"):
            controller.resume("different", run_id="run-1", json_mode=True)

    def test_resume_refuses_an_unknown_non_idempotent_call(self) -> None:
        self._interrupted(idempotent=False)
        controller = AtlasController(max_iterations=1, events=JsonlSink(self.path))

        with self.assertRaisesRegex(ResumeRefused, "non-idempotent"):
            controller.resume("hello", run_id="run-1", json_mode=True)

    def test_resume_refuses_changed_initial_observations(self) -> None:
        self._interrupted()
        controller = AtlasController(max_iterations=1, events=JsonlSink(self.path))

        with self.assertRaisesRegex(ResumeRefused, "observations"):
            controller.resume(
                "hello", run_id="run-1", observations=["different"], json_mode=True
            )

    def test_resume_refuses_a_memory_writer(self) -> None:
        self._interrupted()
        controller = AtlasController(
            max_iterations=1,
            memory_dir=str(Path(self.tmp.name) / "memory"),
            events=JsonlSink(self.path),
        )

        with self.assertRaisesRegex(ResumeRefused, "memory writers"):
            controller.resume("hello", run_id="run-1", json_mode=True)

    def test_resume_refuses_a_run_that_already_stopped(self) -> None:
        controller = AtlasController(events=JsonlSink(self.path))
        controller_run = controller.run("hello", json_mode=True)
        self.assertIsInstance(controller_run, dict)

        with self.assertRaisesRegex(ResumeRefused, "already stopped"):
            controller.resume("hello", run_id=str(controller_run["run_id"]), json_mode=True)

    def test_only_one_process_can_hold_a_run_lock(self) -> None:
        first = RunLock(self.path.with_suffix(".lock"))
        second = RunLock(self.path.with_suffix(".lock"))

        with first:
            with self.assertRaisesRegex(ResumeRefused, "locked"):
                second.acquire()

    def test_run_cannot_bypass_resume_validation_with_private_records(self) -> None:
        self._interrupted()
        records = read_jsonl(self.path)
        controller = AtlasController(max_iterations=1, events=JsonlSink(self.path))

        with self.assertRaisesRegex(ResumeRefused, "only enter through resume"):
            cast(Any, controller.run)(
                "hello", json_mode=True, _resume_records=records
            )
