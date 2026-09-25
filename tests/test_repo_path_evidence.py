"""v1.4: `--repo-path` reads evidence, not prose.

A local repository used to reach a run as formatted text: the evaluator could
not check a claim against it and `inspect` had no source to name. Now the CLI
hands the run an empty `EvidenceBase` bound to one snapshot and a
`FilesystemRepoObserver`, and the run reads through the observer on its own
budget before iteration one. Every read is `Observation.v1`, is logged as
`observation_recorded` and reaches `inspect` with its path and digest.

The negative cases are what make it evidence: a link out of the root is not
read, an oversized file is refused rather than cut, the budget bounds the
reads, a file that changes under the run is re-read as a supersession, and a
credential in a source does not leave through the run document, the log or
the inspection.
"""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import hashlib
from io import StringIO
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any
import unittest

from atlas_core import AtlasController
from atlas_core.adapters.filesystem_repo import FilesystemRepoObserver
from atlas_core.adapters.model import ModelResult
from atlas_core.budget import RunBudget, RunLimits
from atlas_core.cli import main
from atlas_core.eventlog import JsonlSink
from atlas_core.evidence_base import EvidenceBase
from atlas_core.inspect_run import inspect_run, render_inspection
from atlas_core.observation import Observation
from atlas_core.observer import ObservationRequest
from atlas_core.snapshot import take_snapshot
import test_review_plan as review_tests
from test_schemas import SchemaAssertions, load

TASK = "granska repot efter hårdkodade lösenord"
TOKEN = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
LIMITS = RunLimits(
    wall_seconds=30, model_calls=4, tool_calls=8, tokens=100, output_bytes=400_000
)
HAS_SYMLINKS = os.name != "nt"
#: The P1.1 end-to-end test already writes a finding that cites a line; this
#: borrows its helpers rather than a second copy of the findings format.
_WRITER = review_tests.TestTheWholeLoop(
    "test_a_gap_leads_to_a_relevant_read_and_then_a_verified_finding"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class _Recording(FilesystemRepoObserver):
    """The real observer, keeping what it returned so a producer can cite it."""

    def __init__(self, root: Path, **limits: int) -> None:
        super().__init__(root, **limits)
        self.read: list[Observation] = []

    def observe(self, request: ObservationRequest, *, budget: RunBudget) -> list[Observation]:
        found = super().observe(request, budget=budget)
        self.read.extend(found)
        return found


class _Producer:
    """Cites `PASSWORD=admin` from the latest reading of settings.env."""

    def __init__(self, host: _Recording, mutate: Path | None = None) -> None:
        self.host = host
        self.mutate = mutate
        self.calls = 0

    def execute(self, **kwargs: Any) -> ModelResult:
        self.calls += 1
        settings = [o for o in self.host.read if o.path == "settings.env"]
        findings = (
            [_WRITER._finding(settings[-1], "PASSWORD=admin")] if settings else []
        )
        output = _WRITER._output(findings, [o.path for o in settings])
        if self.mutate is not None and self.calls == 1:
            # The ground moves while the model thinks.
            self.mutate.write_text(review_tests.SETTINGS + "EXTRA=1\n", encoding="utf-8")
        return ModelResult(
            output=output, provider="test", model="producer",
            metadata={"usage_tokens": "1"},
        )


class _Repo(SchemaAssertions):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = self.tmp / "repo"
        self.root.mkdir()
        (self.root / "README.md").write_text(review_tests.README, encoding="utf-8")
        (self.root / "settings.env").write_text(review_tests.SETTINGS, encoding="utf-8")
        self.log = self.tmp / "events.jsonl"

    def _cli(self, *extra: str, task: str = TASK) -> tuple[int, dict[str, Any]]:
        out, err = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["run", task, "--repo-path", str(self.root),
                         "--event-log", str(self.log), "--json", *extra])
        return code, json.loads(out.getvalue())

    def _run(self, host: _Recording, producer: Any = None,
             limits: RunLimits = LIMITS) -> dict[str, Any]:
        return AtlasController(
            max_iterations=2, model_adapter=producer, events=JsonlSink(self.log),
        ).run(
            TASK,
            evidence=EvidenceBase(take_snapshot(self.root)),
            observer=host,
            read_first=True,
            limits=limits,
            json_mode=True,
        )

    def _events(self, kind: str) -> list[dict[str, Any]]:
        return [
            record for record in map(json.loads, self.log.read_text().splitlines())
            if record["kind"] == kind
        ]


class TestCliReadsEvidence(_Repo):
    def test_repo_path_reaches_inspect_as_sources_with_path_and_digest(self) -> None:
        code, run = self._cli()
        self.assertIn(code, (0, 2, 3))

        # Observation.v1 bound to the run's snapshot, in the run document.
        started = self._events("run_started")[0]["payload"]
        manifest = run["evidence_manifest"]
        self.assertEqual(manifest["snapshot"]["snapshot_id"], started["snapshot_id"])
        self.assertIn("settings.env", [o["path"] for o in manifest["observations"]])

        # Logged before iteration one, with the path.
        first = self._events("observation_recorded")[0]
        self.assertEqual(first["iteration"], 0)
        self.assertIn("settings.env", [item["path"] for item in first["payload"]["added"]])

        # And in inspect: sources for old consumers, details for new ones.
        report = inspect_run(self.log, run["run_id"])
        self.assert_matches(load("atlas-inspect.v1.json"), report, "inspect")
        details = {item["path"]: item for item in report["source_details"]}
        self.assertEqual(details["settings.env"]["content_sha256"],
                         _sha256(self.root / "settings.env"))
        self.assertEqual(sorted(report["sources"]),
                         sorted(item["source_id"] for item in report["source_details"]))
        self.assertIn("settings.env  sha256:", render_inspection(report))

    def test_an_unnarrowed_task_still_reads_the_fixed_surface(self) -> None:
        code, run = self._cli(task="gör något bra")
        self.assertIn(code, (0, 2, 3))
        paths = [o["path"] for o in run["evidence_manifest"]["observations"]]
        self.assertEqual(paths, ["README.md"])

    def test_a_repo_path_that_is_not_a_directory_is_refused(self) -> None:
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit) as raised:
            main(["run", TASK, "--repo-path", str(self.tmp / "saknas"), "--json"])
        self.assertEqual(raised.exception.code, 2)

    def test_budget_bounds_the_reads(self) -> None:
        (self.root / "config.env").write_text("A=1\n", encoding="utf-8")
        code, run = self._cli("--max-tool-calls", "1")
        self.assertEqual(code, 2)
        self.assertEqual(run["stop_reason"], "budget_exhausted")
        self.assertEqual(run["metadata"]["budget_exhausted"], "tool_calls")
        self.assertEqual(run["evaluations"], [])
        self.assertEqual(self._events("call_finished")[0]["payload"]["outcome"], "denied")
        self.assertEqual(self._events("run_stopped")[0]["payload"]["stop_reason"],
                         "budget_exhausted")

    def test_a_credential_in_a_source_does_not_leave(self) -> None:
        (self.root / "settings.env").write_text(f"API_TOKEN={TOKEN}\n", encoding="utf-8")
        _, run = self._cli()
        report = inspect_run(self.log, run["run_id"])
        self.assertIn("settings.env", [item["path"] for item in report["source_details"]])
        for label, text in (("run", json.dumps(run)), ("log", self.log.read_text()),
                            ("inspect", json.dumps(report))):
            self.assertNotIn(TOKEN, text, label)


class TestTheObserverRefuses(_Repo):
    @unittest.skipUnless(HAS_SYMLINKS, "symlinks unavailable")
    def test_a_link_out_of_the_root_is_not_read(self) -> None:
        outside = self.tmp / "hemligt.env"
        outside.write_text(f"TOKEN={TOKEN}\nUTANFÖR ROTEN\n", encoding="utf-8")
        (self.root / "stolen.env").symlink_to(outside)

        _, run = self._cli()

        paths = [o["path"] for o in run["evidence_manifest"]["observations"]]
        self.assertNotIn("stolen.env", paths)
        self.assertNotIn("hemligt.env", " ".join(paths))
        for text in (json.dumps(run), self.log.read_text()):
            self.assertNotIn("UTANFÖR ROTEN", text)

    def test_an_oversized_source_is_refused_not_cut(self) -> None:
        (self.root / "settings.env").write_text("X=" + "y" * 4096 + "\n", encoding="utf-8")
        host = _Recording(self.root, max_bytes_per_file=1024)
        run = self._run(host)
        paths = [o.path for o in host.read]
        self.assertNotIn("settings.env", paths)
        self.assertNotIn(
            "settings.env",
            [o["path"] for o in run["evidence_manifest"]["observations"]],
        )

    def test_one_round_reads_at_most_its_file_limit(self) -> None:
        for index in range(5):
            (self.root / f"extra{index}.env").write_text("A=1\n", encoding="utf-8")
        host = _Recording(self.root, max_files_per_round=2)
        run = self._run(host)
        first_round = run["metadata"]["observation_rounds"][0]
        self.assertEqual(first_round["requested"], 2)

    def test_a_broad_pattern_does_not_crowd_out_the_others(self) -> None:
        # `*.env` matches six files; `config*` must still get its read.
        for index in range(5):
            (self.root / f"a{index}.env").write_text("A=1\n", encoding="utf-8")
        (self.root / "config.toml").write_text("x = 1\n", encoding="utf-8")
        host = _Recording(self.root, max_files_per_round=3)
        self._run(host)
        self.assertIn("config.toml", [o.path for o in host.read])

    @unittest.skipIf(os.name != "posix" or os.geteuid() == 0, "needs a non-root POSIX user")
    def test_an_unreadable_file_is_skipped_not_fatal(self) -> None:
        locked = self.root / "locked.env"
        locked.write_text("A=1\n", encoding="utf-8")
        locked.chmod(0)
        self.addCleanup(locked.chmod, 0o644)
        host = _Recording(self.root)
        run = self._run(host)
        self.assertNotEqual(run["stop_reason"], "tool_error")
        self.assertEqual({"settings.env"}, {o.path for o in host.read} - {"README.md"})

    @unittest.skipUnless(HAS_SYMLINKS, "symlinks unavailable")
    def test_links_out_of_the_root_cost_no_quota(self) -> None:
        outside = self.tmp / "ute.txt"
        outside.write_text("UTE\n", encoding="utf-8")
        for index in range(4):
            (self.root / f"a{index}.env").symlink_to(outside)
        host = _Recording(self.root, max_files_per_round=1)
        run = self._run(host)
        self.assertEqual([o.path for o in host.read], ["settings.env"])
        self.assertEqual(run["metadata"]["budget_usage"]["tool_calls"], 1)


@unittest.skipUnless(os.name == "posix", "POSIX process-group guard")
class TestPublicCli(_Repo):
    def test_a_missing_repo_path_is_a_usage_error_not_a_lost_worker(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "atlas_core.cli", "run", TASK,
             "--repo-path", str(self.tmp / "saknas"), "--event-log", str(self.log),
             "--json"],
            capture_output=True, timeout=60,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn(b"--repo-path is not a directory", result.stderr)
        self.assertFalse(self.log.exists())

    def test_the_worker_path_reads_evidence_too(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "atlas_core.cli", "run", TASK,
             "--repo-path", str(self.root), "--event-log", str(self.log), "--json"],
            capture_output=True, timeout=60,
        )
        run = json.loads(result.stdout)
        report = inspect_run(self.log, run["run_id"])
        self.assertIn("settings.env", [item["path"] for item in report["source_details"]])


class TestARoundIsAcceptedWhole(_Repo):
    def test_a_round_the_output_budget_cannot_pay_for_is_not_adopted(self) -> None:
        code, run = self._cli("--max-output-bytes", "40")
        self.assertEqual(code, 2)
        self.assertEqual(run["stop_reason"], "budget_exhausted")
        self.assertEqual(run["metadata"]["budget_exhausted"], "output_bytes")
        # Read and paid for in tool calls, but not accepted: no evidence, no
        # recorded round, no context.
        self.assertEqual(run["evidence_manifest"]["observations"], [])
        self.assertNotIn("observation_rounds", run["metadata"])
        self.assertEqual(run["observations"], [])
        self.assertEqual(self._events("observation_recorded"), [])
        self.assertEqual(self._events("call_finished")[0]["payload"]["outcome"], "denied")
        self.assertEqual(inspect_run(self.log, run["run_id"])["source_details"], [])


class TestResumeRereadsTheSameBytes(_Repo):
    """`run_started` binds the empty base; the bytes arrive in the first
    round. A resume replays that round, so it has to read the same bytes."""

    def _interrupted_after_the_first_read(self) -> str:
        run = self._run(_Recording(self.root))
        records = self.log.read_text().splitlines()
        kinds = [json.loads(line)["kind"] for line in records]
        keep = records[: kinds.index("observation_recorded") + 1]
        self.log.write_text("\n".join(keep) + "\n", encoding="utf-8")
        return str(run["run_id"])

    def _resume(self, run_id: str) -> dict[str, Any]:
        return AtlasController(max_iterations=2, events=JsonlSink(self.log)).resume(
            TASK, run_id=run_id,
            evidence=EvidenceBase(take_snapshot(self.root)),
            observer=_Recording(self.root), read_first=True,
            limits=LIMITS, json_mode=True,
        )  # type: ignore[return-value]

    def test_a_source_changed_since_the_interrupted_read_stops_the_resume(self) -> None:
        run_id = self._interrupted_after_the_first_read()
        (self.root / "settings.env").write_text("PASSWORD=annat\n", encoding="utf-8")

        run = self._resume(run_id)

        self.assertEqual(run["stop_reason"], "blocked")
        changed = run["metadata"]["resume_evidence_changed"]
        self.assertEqual(changed["round"], 0)
        settings = [o for o in _Recording(self.root).observe(
            _first_request(self.root), budget=_budget()) if o.path == "settings.env"]
        self.assertIn(settings[0].source_id, changed["source_ids"])
        # Nothing from the changed read was adopted.
        self.assertEqual(run["evidence_manifest"]["observations"], [])
        self.assertEqual(len(self._events("observation_recorded")), 1)

    def test_unchanged_sources_resume_normally(self) -> None:
        run_id = self._interrupted_after_the_first_read()

        run = self._resume(run_id)

        self.assertNotIn("resume_evidence_changed", run["metadata"])
        self.assertNotEqual(run["stop_reason"], "blocked")
        self.assertEqual(len(self._events("observation_recorded")), 2)


def _first_request(root: Path) -> ObservationRequest:
    from atlas_core.observer import request_from

    return request_from(take_snapshot(root), [], [], [], 0, patterns=["*.env"])


def _budget() -> RunBudget:
    return RunBudget(LIMITS)


class TestEvaluationUsesTheEvidence(_Repo):
    def test_a_claim_about_a_read_file_is_verified_against_its_bytes(self) -> None:
        host = _Recording(self.root)
        producer = _Producer(host)
        run = self._run(host, producer)
        self.assertEqual(producer.calls, 1)
        self.assertEqual(run["stop_reason"], "passed")
        record = run["evaluations"][-1]["citation_checks"][0]
        self.assertEqual(record["verdict"], "verified")
        self.assertIn("PASSWORD=admin", record["statuses"][0]["quoted"])

    def test_a_file_changed_after_observation_is_reread_as_a_supersession(self) -> None:
        host = _Recording(self.root)
        producer = _Producer(host, mutate=self.root / "settings.env")
        before = _sha256(self.root / "settings.env")
        run = self._run(host, producer)
        after = _sha256(self.root / "settings.env")

        superseded = [
            item for record in self._events("observation_recorded")
            for item in record["payload"]["superseded"]
        ]
        self.assertEqual(
            [(s["path"], s["previous_sha256"], s["new_sha256"]) for s in superseded],
            [("settings.env", before, after)],
        )
        # inspect names the bytes the run went on with.
        report = inspect_run(self.log, run["run_id"])
        details = {item["path"]: item for item in report["source_details"]}
        self.assertEqual(details["settings.env"]["content_sha256"], after)
        # The first grade rested on bytes that moved; it is not the outcome.
        self.assertEqual(producer.calls, 2)
        self.assertEqual(run["stop_reason"], "passed")


if __name__ == "__main__":
    unittest.main()
