from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import random
import tempfile
import unittest

from atlas_core import AtlasController, JsonlSink
from atlas_core.eventlog import EventLog, ResumeRefused, read_jsonl
from atlas_core.machine import TRANSITIONS, InvalidTransition, check_transition


class TestStateTransitionProperties(unittest.TestCase):
    def test_random_invalid_transitions_fail_closed(self) -> None:
        rng = random.Random(1304)
        states = tuple(TRANSITIONS)
        for _ in range(500):
            current = rng.choice(states)
            target = rng.choice(states)
            allowed = target in TRANSITIONS[current]
            if allowed:
                check_transition(current, target)
            else:
                with self.assertRaises(InvalidTransition):
                    check_transition(current, target)


class TestMalformedEventFuzz(unittest.TestCase):
    def test_mutated_event_contracts_are_rejected(self) -> None:
        base = EventLog("run-1")
        records = [base.append("run_started").to_dict()]
        mutations = (
            {"schema": "atlas-event.v0"},
            {"run_id": ""},
            {"sequence": -1},
            {"kind": "invented"},
            {"call_id": "not-allowed"},
        )
        for mutation in mutations:
            damaged = dict(records[0])
            damaged.update(mutation)
            with self.subTest(mutation=mutation):
                with self.assertRaises((ResumeRefused, ValueError)):
                    EventLog("run-1", previous=[damaged])


class TestParallelRuns(unittest.TestCase):
    def test_parallel_runs_keep_ids_sequences_and_files_separate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def execute(index: int) -> tuple[str, Path]:
                path = root / f"run-{index}.jsonl"
                result = AtlasController(
                    max_iterations=1, events=JsonlSink(path)
                ).run(f"question {index}", json_mode=True)
                return result["run_id"], path

            with ThreadPoolExecutor(max_workers=8) as pool:
                completed = list(pool.map(execute, range(24)))

            run_ids = [run_id for run_id, _path in completed]
            self.assertEqual(len(set(run_ids)), len(run_ids))
            for run_id, path in completed:
                records = read_jsonl(path)
                self.assertEqual({record["run_id"] for record in records}, {run_id})
                self.assertEqual(
                    [record["sequence"] for record in records], list(range(len(records)))
                )
                self.assertEqual(records[-1]["kind"], "run_stopped")


if __name__ == "__main__":
    unittest.main()
