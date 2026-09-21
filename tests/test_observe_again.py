"""P1.1: the loop reads again, mid-run, and evidence still means what it meant.

The contract these tests lock:

1. One snapshot per run. Every new observation binds to it and carries its own
   provenance. A source that changed is not swapped in silently.
2. `next_action: observe_again` leads to an actual read-only read through the
   host, under the same budget and deadline as the rest of the run.
3. A retry needs new relevant material. Rewording is not material, and neither
   is re-reading a file that has not moved. When nothing new can be observed
   the run stops with a stop reason that says so.
4. Fail closed. A timeout, an unreachable source or a broken snapshot binding
   never becomes a verified finding.

The end-to-end case is the one that matters: iteration 1 names a concrete
evidence gap, the host reads, and iteration 2 grades against *that* reading.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any

from atlas_core import AtlasController
from atlas_core.adapters.model import ModelResult
from atlas_core.budget import BudgetExceeded, RunLimits
from atlas_core.claim_check import ClaimKind, TypedClaim
from atlas_core.evidence import FINDINGS_FENCE
from atlas_core.evidence_base import EvidenceBase
from atlas_core.observation import Observation
from atlas_core.observer import ObservationRequest
from atlas_core.snapshot import collect_observation, take_snapshot

FIRST = "# Atlas Core\n\nEn avgränsad loop-motor.\n"
REWRITTEN = "# Atlas Core\n\npip install atlas-core\n\nEn avgränsad loop-motor.\n"

REPO_TASK = "granska repo atlas-core"

PROSE = """# Repogranskning

Granskningen nedan bygger på de källor som lästes denna körning och går igenom
repots dokumentation, testupplägg och släppprocess i tillräcklig detalj för att
motivera de slutsatser som dras. Texten är avsiktligt lång nog för att passera
substanskravet, eftersom poängen är vad loopen gör när underlaget inte räcker.

## Observed sources
- `README.md`

## Findings
- {claim}

## Recommendation
Lägg till ett installationsavsnitt.

## Next step
Skriv avsnittet.

## Confidence
Hög.
"""

LIMITS = RunLimits(
    wall_seconds=30, model_calls=6, tool_calls=0, tokens=100, output_bytes=400_000
)


class _Host:
    """A host that re-reads on request, and records what it was asked."""

    def __init__(self, root: Path, snapshot: Any, *, stale: list[Observation] | None = None):
        self.root = root
        self.snapshot = snapshot
        #: When given, the host hands these back instead of reading again —
        #: the shape of a host that answered without anything having moved.
        self.stale = stale
        self.requests: list[ObservationRequest] = []
        self.returned: list[list[Observation]] = []

    def observe(self, request: ObservationRequest) -> list[Observation]:
        self.requests.append(request)
        fresh = (
            list(self.stale)
            if self.stale is not None
            else [collect_observation(self.snapshot, path) for path in request.paths]
        )
        self.returned.append(fresh)
        return fresh


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (self.root / "README.md").write_text(FIRST, encoding="utf-8")
        self.snapshot = take_snapshot(self.root)
        self.observation = collect_observation(self.snapshot, "README.md")
        self.base = EvidenceBase(
            snapshot=self.snapshot, observations=[self.observation]
        )
        self.host = _Host(self.root, self.snapshot)

    # -- output builders ---------------------------------------------------

    def _finding(self, observation: Observation, text: str) -> dict[str, Any]:
        typed = TypedClaim(
            kind=ClaimKind.CONTAINS, source_id=observation.source_id, text=text
        )
        claim = typed.render(
            observation.path, observation.line_start, observation.line_end
        )
        line = next(
            index + 1
            for index, content in enumerate(observation.excerpt.splitlines())
            if text in content
        )
        return {
            "claim": claim,
            "scope": observation.path,
            "severity": "P2",
            "severity_rationale": "Första raden en ny användare läser.",
            "evidence": [
                {
                    "source_id": observation.source_id,
                    "content_sha256": observation.content_sha256,
                    "line_start": line,
                    "line_end": line,
                    "quoted": observation.excerpt.splitlines()[line - 1],
                }
            ],
            "typed_claim": {
                "kind": typed.kind.value,
                "source_id": typed.source_id,
                "text": typed.text,
            },
        }

    def _block(self, finding: dict[str, Any]) -> str:
        return (
            PROSE.format(claim=finding["claim"])
            + "\n```"
            + FINDINGS_FENCE
            + "\n"
            + json.dumps([finding])
            + "\n```\n"
        )

    def _stale_output(self) -> str:
        """Cites the README as it was read, which is about to stop being true."""
        return self._block(self._finding(self.observation, "# Atlas Core"))

    def _run(self, adapter: Any, *, observer: Any = None, iterations: int = 2) -> dict:
        return AtlasController(
            max_iterations=iterations, model_adapter=adapter
        ).run(
            REPO_TASK,
            evidence=self.base,
            json_mode=True,
            limits=LIMITS,
            observer=observer,
        )


class TestTheLoopReadsAgain(_Base):
    """The end-to-end case: a gap, a read, and a second pass that uses it."""

    def test_iteration_two_grades_against_what_the_host_just_read(self) -> None:
        outputs: list[str] = []
        test = self

        class _Producer:
            """Cites the run's current reading of the README each time.

            It has to be told nothing: on the second pass the evidence base
            holds the re-read observation, and a finding that cites the old
            digest would fail. Building the citation from what the run holds
            *now* is what "iteration 2 uses that observation" means.
            """

            def __init__(self) -> None:
                self.calls = 0

            def execute(self, **kwargs: Any) -> ModelResult:
                self.calls += 1
                if self.calls == 1:
                    current, text = test.observation, "# Atlas Core"
                else:
                    # What the host just read. A citation built from the run's
                    # earlier reading would fail `digest_mismatch`, which is
                    # what makes this assertion mean "iteration 2 used the new
                    # observation" rather than "iteration 2 happened".
                    current, text = test.host.returned[-1][0], "pip install"
                    prose = "\n".join(kwargs.get("observations") or [])
                    test.assertIn(
                        "pip install", prose, "the new reading reaches the producer"
                    )
                output = test._block(test._finding(current, text))
                outputs.append(output)
                return ModelResult(
                    output=output,
                    provider="test",
                    model="producer",
                    metadata={"usage_tokens": "1"},
                )

        producer = _Producer()
        # The file changes after the run's observation was taken, so iteration
        # one is graded against a source that has moved.
        (self.root / "README.md").write_text(REWRITTEN, encoding="utf-8")

        run = self._run(producer, observer=self.host)

        self.assertEqual(producer.calls, 2, "the run must take a second pass")
        self.assertEqual(len(self.host.requests), 1)
        self.assertEqual(run["stop_reason"], "passed")

        round_record = run["metadata"]["observation_rounds"][0]
        self.assertEqual(
            round_record["superseded"][0]["source_id"], self.observation.source_id
        )
        # The second pass was graded against the re-read bytes, not the first.
        citation = run["evaluations"][-1]["citation_checks"][0]["statuses"][0]
        self.assertEqual(citation["status"], "intact")
        self.assertIn("pip install", citation["quoted"])
        self.assertEqual(run["evaluations"][-1]["citation_checks"][0]["verdict"], "verified")

    def test_the_host_is_told_which_sources_and_why(self):
        (self.root / "README.md").write_text(REWRITTEN, encoding="utf-8")

        self._run(_Fixed(self._stale_output()), observer=self.host)

        request = self.host.requests[0]
        self.assertEqual(request.snapshot.snapshot_id, self.snapshot.snapshot_id)
        self.assertEqual(request.paths, ["README.md"])
        self.assertEqual(request.source_ids, [self.observation.source_id])
        self.assertIn("stale_source", request.blocked_by)
        self.assertTrue(request.claims)

    def test_the_old_reading_is_superseded_and_not_silently_replaced(self):
        (self.root / "README.md").write_text(REWRITTEN, encoding="utf-8")

        run = self._run(_Fixed(self._stale_output()), observer=self.host)

        record = run["metadata"]["observation_rounds"][0]["superseded"][0]
        self.assertEqual(record["previous_sha256"], self.observation.content_sha256)
        self.assertNotEqual(record["new_sha256"], self.observation.content_sha256)
        self.assertEqual(record["path"], "README.md")
        # The lines the first pass rested on survive in its own evaluation, so
        # the replacement did not erase what was graded before it.
        first = run["evaluations"][0]["citation_checks"][0]["statuses"][0]
        self.assertIn("# Atlas Core", first["quoted"])

    def test_reading_again_is_the_state_the_machine_already_names(self):
        """`observing` means the run is reading. It means that mid-loop too."""
        from atlas_core.machine import TRANSITIONS

        self.assertIn("observing", TRANSITIONS["evaluating"])
        self.assertIn("replanning", TRANSITIONS["observing"])

        (self.root / "README.md").write_text(REWRITTEN, encoding="utf-8")
        run = self._run(_Fixed(self._stale_output()), observer=self.host)

        self.assertEqual(run["metadata"]["observation_rounds"][0]["iteration"], 1)


class TestNothingNewIsNotARetry(_Base):
    def test_a_host_that_returns_nothing_stops_the_run(self):
        class _Empty:
            def __init__(self) -> None:
                self.calls = 0

            def observe(self, request: ObservationRequest) -> list[Observation]:
                self.calls += 1
                return []

        (self.root / "README.md").write_text(REWRITTEN, encoding="utf-8")
        adapter = _Fixed(self._stale_output())
        observer = _Empty()

        run = self._run(adapter, observer=observer, iterations=3)

        self.assertEqual(observer.calls, 1)
        self.assertEqual(adapter.calls, 1, "no iteration is spent on the same evidence")
        self.assertEqual(run["stop_reason"], "blocked")
        self.assertFalse(run["metadata"]["observation_rounds"][0]["added"])

    def test_re_reading_an_unchanged_source_is_not_new_material(self):
        """The host answered, and the answer changes nothing the run can check."""
        (self.root / "README.md").write_text(REWRITTEN, encoding="utf-8")
        adapter = _Fixed(self._stale_output())
        host = _Host(self.root, self.snapshot, stale=[self.observation])

        run = self._run(adapter, observer=host, iterations=3)

        self.assertEqual(adapter.calls, 1)
        self.assertEqual(run["stop_reason"], "blocked")
        round_record = run["metadata"]["observation_rounds"][0]
        self.assertEqual(round_record["unchanged"], [self.observation.source_id])
        self.assertFalse(round_record["superseded"])

    def test_without_an_observer_the_run_behaves_as_before(self):
        """Negative control: the gate is the observer, not a new failure mode."""
        (self.root / "README.md").write_text(REWRITTEN, encoding="utf-8")

        run = self._run(_Fixed(self._stale_output()))

        self.assertEqual(run["stop_reason"], "blocked")
        self.assertNotIn("observation_rounds", run["metadata"])


class TestFailClosed(_Base):
    def test_a_host_that_raises_ends_the_run_as_a_runtime_failure(self):
        class _Boom:
            def observe(self, request: ObservationRequest) -> list[Observation]:
                raise TimeoutError("source unreachable")

        (self.root / "README.md").write_text(REWRITTEN, encoding="utf-8")

        run = self._run(_Fixed(self._stale_output()), observer=_Boom())

        self.assertEqual(run["stop_reason"], "tool_error")
        self.assertEqual(run["stop_class"], "runtime")
        self.assertEqual(run["metadata"]["failure"]["stage"], "observer")
        self.assertEqual(run["metadata"]["failure"]["error"], "TimeoutError")

    def test_an_observation_from_another_snapshot_is_refused(self):
        """The one door a host must not be able to open."""
        other = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, other, True)
        (other / "README.md").write_text(REWRITTEN, encoding="utf-8")
        foreign = take_snapshot(other)

        class _Foreign:
            def observe(self, request: ObservationRequest) -> list[Observation]:
                return [collect_observation(foreign, "README.md")]

        (self.root / "README.md").write_text(REWRITTEN, encoding="utf-8")

        run = self._run(_Fixed(self._stale_output()), observer=_Foreign())

        self.assertEqual(run["stop_reason"], "tool_error")
        self.assertEqual(run["metadata"]["failure"]["stage"], "observer")
        self.assertIn("snapshot", run["metadata"]["failure"]["message"])

    def test_a_failed_round_produces_no_finding_and_no_grade(self):
        """Fail closed: a runtime failure is not a verdict about an answer."""
        class _Boom:
            def observe(self, request: ObservationRequest) -> list[Observation]:
                raise OSError("disk went away")

        (self.root / "README.md").write_text(REWRITTEN, encoding="utf-8")

        run = self._run(_Fixed(self._stale_output()), observer=_Boom())

        self.assertEqual(len(run["evaluations"]), 1, "the failed round is not graded")
        self.assertFalse(run["evaluations"][0]["passed"])

    def test_an_exhausted_budget_during_a_round_is_not_a_tool_error(self):
        """A limit is a control stop; the machinery did not fail."""
        class _Greedy:
            def observe(self, request: ObservationRequest) -> list[Observation]:
                raise BudgetExceeded("wall_seconds")

        (self.root / "README.md").write_text(REWRITTEN, encoding="utf-8")

        run = self._run(_Fixed(self._stale_output()), observer=_Greedy())

        self.assertEqual(run["stop_reason"], "budget_exhausted")
        self.assertEqual(run["stop_class"], "control")

    def test_an_unbudgeted_run_refuses_an_observer(self):
        """Same rule as Atlas-managed readers: no unmetered host reads."""
        with self.assertRaisesRegex(ValueError, "RunLimits"):
            AtlasController(max_iterations=2, model_adapter=_Fixed("x")).run(
                REPO_TASK, evidence=self.base, observer=self.host, json_mode=True
            )

    def test_the_round_is_charged_to_the_run_budget(self):
        """Same budget as the rest of the run, not a free side channel."""
        (self.root / "README.md").write_text(REWRITTEN, encoding="utf-8")
        output = self._stale_output()

        without = self._run(_Fixed(output))
        with_round = self._run(_Fixed(output), observer=self.host)

        self.assertGreater(
            with_round["metadata"]["budget_usage"]["output_bytes"],
            without["metadata"]["budget_usage"]["output_bytes"],
        )


class _Fixed:
    def __init__(self, output: str):
        self.output = output
        self.calls = 0

    def execute(self, **kwargs: Any) -> ModelResult:
        self.calls += 1
        return ModelResult(
            output=self.output,
            provider="test",
            model="fixed",
            metadata={"usage_tokens": "1"},
        )


if __name__ == "__main__":
    unittest.main()
