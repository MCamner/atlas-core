"""P1.1 box two: two fixture repos, an answer key, and what the numbers say.

`tests/fixtures/repo_with_defects` holds three known defects, each written as a
predicate the deterministic checker can settle.
`tests/fixtures/repo_without_defects` holds the same three files with none of
them. A run that reports a defect there has invented one.

What is being measured is the **gate**, not a finder. Atlas Core ships no live
model, so the findings in a run are whatever its producer emitted. The question
these tests answer is whether the loop establishes what the source supports,
refuses what it contradicts, and declines to dress up the rest — and whether
the measurement says so in numbers rather than in prose.

The metric that is easy to leave out has its own class at the bottom: a review
that asserts nothing passes, at a full score, and a reader who stops at
`Status: passed` will take that for a clean bill of health. It is not one.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

from atlas_core import AtlasController
from atlas_core.adapters.model import ModelResult
from atlas_core.benchmark import GroundTruth, measure
from atlas_core.budget import RunLimits
from atlas_core.claim_check import ClaimKind, TypedClaim
from atlas_core.evidence import FINDINGS_FENCE
from atlas_core.evidence_base import EvidenceBase
from atlas_core.finalizer import render_run_text
from atlas_core.observation import Observation
from atlas_core.snapshot import collect_observation, take_snapshot

FIXTURES = Path(__file__).resolve().parent / "fixtures"
WITH_DEFECTS = FIXTURES / "repo_with_defects"
WITHOUT_DEFECTS = FIXTURES / "repo_without_defects"

REPO_TASK = "granska repo och hitta defekter"

#: The same fixture, asked a question the plan can narrow. `REPO_TASK` cannot
#: be narrowed — no topic's keywords appear in it — so every run above is
#: graded on the route's criteria alone and none of them reaches
#: `findings_are_on_topic`. What an empty review is worth therefore depends on
#: which of the two it was asked, and the benchmark has to measure both or it
#: describes half the gate.
SECRETS_TASK = "granska repot efter hårdkodade lösenord"

PROSE = """# Repogranskning

Granskningen nedan bygger på de källor som lästes denna körning och går igenom
repots dokumentation, deployskript och konfiguration i tillräcklig detalj för
att motivera de slutsatser som dras.

## Observed sources
{sources}

## Findings
{findings}

## Recommendation
Åtgärda det som står ovan.

## Next step
Läs om filerna efter åtgärd.

## Confidence
Hög.
"""

LIMITS = RunLimits(
    wall_seconds=30, model_calls=4, tool_calls=0, tokens=100, output_bytes=400_000
)


class _Adapter:
    def __init__(self, output: str):
        self.output = output
        self.calls = 0

    def execute(self, **kwargs: Any) -> ModelResult:
        self.calls += 1
        return ModelResult(
            output=self.output,
            provider="benchmark",
            model="scripted",
            metadata={"usage_tokens": "1"},
        )


class _Host:
    """Resolves a review plan's patterns against the fixture directory."""

    def __init__(self, root: Path, snapshot: Any):
        self.root = root
        self.snapshot = snapshot

    def observe(self, request: Any, *, budget: object = None) -> list[Observation]:
        from fnmatch import fnmatch

        names = sorted(
            path.name
            for path in self.root.iterdir()
            if path.is_file()
            and path.name != "ground_truth.json"
            and any(fnmatch(path.name, pattern) for pattern in request.patterns)
        )
        return [collect_observation(self.snapshot, name) for name in names]


class _Fixture(unittest.TestCase):
    """One fixture repo, read for real, with its answer key loaded."""

    root: Path

    def setUp(self) -> None:
        self.snapshot = take_snapshot(self.root)
        self.observations = {
            name: collect_observation(self.snapshot, name)
            for name in ("README.md", "deploy.sh", "settings.env")
        }
        self.base = EvidenceBase(
            snapshot=self.snapshot, observations=list(self.observations.values())
        )
        self.truth = GroundTruth.load(self.root / "ground_truth.json")

    # -- building a producer's output --------------------------------------

    def _finding(self, path: str, kind: ClaimKind, text: str) -> dict[str, Any]:
        """A finding asserting one predicate, cited from the real observation."""
        observation = self.observations[path]
        typed = TypedClaim(
            kind=kind, source_id=observation.source_id, text=text
        )
        claim = typed.render(
            observation.path, observation.line_start, observation.line_end
        )
        return {
            "claim": claim,
            "scope": path,
            "severity": "P1",
            "severity_rationale": "Mätfixtur.",
            "evidence": [self._citation(observation)],
            "typed_claim": {
                "kind": typed.kind.value,
                "source_id": typed.source_id,
                "text": typed.text,
            },
        }

    def _citation(self, observation: Observation) -> dict[str, Any]:
        return {
            "source_id": observation.source_id,
            "content_sha256": observation.content_sha256,
            "line_start": 1,
            "line_end": 1,
            "quoted": observation.excerpt.splitlines()[0],
        }

    def _output(
        self, findings: list[dict[str, Any]], *, prose_claims: list[str] | None = None
    ) -> str:
        lines = [f"- {finding['claim']}" for finding in findings]
        lines += [f"- {claim}" for claim in (prose_claims or [])]
        # No bullets at all when there is nothing to report. A line saying
        # "no findings" *is* a finding as far as the evaluator is concerned —
        # it is prose under the findings heading — and an empty review has to
        # be genuinely empty for this fixture to measure what it claims to.
        text = PROSE.format(
            sources="\n".join(f"- `{name}`" for name in self.observations),
            findings="\n".join(lines),
        )
        if not findings:
            # No machine-readable block at all: the shape of an output that
            # asserts only prose, or nothing.
            return text
        return (
            text + "\n```" + FINDINGS_FENCE + "\n" + json.dumps(findings) + "\n```\n"
        )

    def _measure(self, output: str, *, iterations: int = 1) -> Any:
        adapter = _Adapter(output)
        run = AtlasController(max_iterations=iterations, model_adapter=adapter).run(
            REPO_TASK, evidence=self.base, json_mode=True, limits=LIMITS
        )
        self.run_document = run
        return measure(run, self.truth)

    def _measure_narrowed(self, output: str) -> Any:
        """The same output, under a task the plan can narrow to a topic.

        Two iterations and a host, because a narrowed plan names patterns this
        repository may not have — only a host can establish that there is no
        `config*` here — and the question is graded once that is settled.
        """
        adapter = _Adapter(output)
        run = AtlasController(max_iterations=2, model_adapter=adapter).run(
            SECRETS_TASK,
            evidence=self.base,
            json_mode=True,
            limits=LIMITS,
            observer=_Host(self.root, self.snapshot),
        )
        self.run_document = run
        return measure(run, self.truth)

    def _measure_from_nothing(self, output: str) -> Any:
        """The chain box one promised, measured end to end.

        The run starts with the snapshot and **no observations at all**. The
        plan narrows to credentials and names `*.env`; nothing has been read,
        so the gap is real rather than arranged. The host resolves the
        patterns, and the second pass is graded against whatever that read
        brought back.

        `_measure_narrowed` starts with all three files already in hand, which
        measures the gate and not the reading. This measures both.
        """
        adapter = _Adapter(output)
        run = AtlasController(max_iterations=2, model_adapter=adapter).run(
            SECRETS_TASK,
            evidence=EvidenceBase(snapshot=self.snapshot),
            json_mode=True,
            limits=LIMITS,
            observer=_Host(self.root, self.snapshot),
        )
        self.run_document = run
        return measure(run, self.truth)

    def _all_true_findings(self) -> list[dict[str, Any]]:
        return [
            self._finding("README.md", ClaimKind.LACKS, "## Installation"),
            self._finding("deploy.sh", ClaimKind.CONTAINS, "TODO"),
            self._finding("settings.env", ClaimKind.CONTAINS, "PASSWORD=admin"),
        ]


class TestTheRepoWithDefects(_Fixture):
    root = WITH_DEFECTS

    def test_a_run_that_finds_all_three_scores_them_all(self):
        result = self._measure(self._output(self._all_true_findings()))

        self.assertEqual(sorted(result.found_defects), ["D1", "D2", "D3"])
        self.assertEqual(result.missed_defects, [])
        self.assertEqual(result.precision, 1.0)
        self.assertEqual(result.recall, 1.0)
        self.assertEqual(result.evidence_backed_share, 1.0)
        self.assertEqual(result.stop_reason, "passed")

    def test_a_run_that_finds_one_is_measured_as_finding_one(self):
        result = self._measure(
            self._output([self._finding("deploy.sh", ClaimKind.CONTAINS, "TODO")])
        )

        self.assertEqual(result.found_defects, ["D2"])
        self.assertEqual(sorted(result.missed_defects), ["D1", "D3"])
        self.assertEqual(result.recall, 0.33)
        self.assertEqual(result.precision, 1.0)

    def test_a_true_claim_that_is_not_a_defect_is_counted_apart(self):
        """Noise, not a lie, and it needs a different fix from a refutation."""
        findings = self._all_true_findings()
        findings.append(self._finding("README.md", ClaimKind.CONTAINS, "# Demorepo"))

        result = self._measure(self._output(findings))

        self.assertEqual(result.verified_non_defects, 1)
        self.assertEqual(sorted(result.found_defects), ["D1", "D2", "D3"])
        self.assertEqual(result.precision, 0.75)
        self.assertEqual(result.refuted, 0)

    def test_prose_findings_are_counted_as_asserted_and_not_as_backed(self):
        result = self._measure(
            self._output(
                self._all_true_findings(),
                prose_claims=["Repot verkar ha svag testtäckning."],
            )
        )

        self.assertEqual(result.asserted, 4)
        self.assertEqual(result.verified, 3)
        self.assertEqual(result.unestablished, 1)
        self.assertEqual(result.evidence_backed_share, 0.75)
        self.assertFalse(result.passed)

    def test_the_cost_and_the_stop_reason_are_recorded(self):
        """The roadmap asks for both, and a benchmark without them is a score."""
        result = self._measure(self._output(self._all_true_findings()))

        self.assertEqual(result.iterations, 1)
        self.assertEqual(result.stop_reason, "passed")
        self.assertGreater(result.cost["output_bytes"], 0)
        self.assertGreaterEqual(result.cost["model_calls"], 1)


class TestTheRepoWithoutDefects(_Fixture):
    root = WITHOUT_DEFECTS

    def test_an_invented_defect_is_refuted_not_reported(self):
        """The whole point of the clean fixture.

        The same three claims that are true of the other repo are false here,
        and each names a real file with a real citation. Only comparing them
        against the source tells them apart.
        """
        result = self._measure(self._output(self._all_true_findings()))

        self.assertEqual(result.refuted, 3)
        self.assertEqual(result.verified, 0)
        self.assertEqual(result.found_defects, [])
        self.assertFalse(result.passed)

    def test_precision_is_none_rather_than_zero_when_nothing_was_established(self):
        """A run that established nothing has no precision to report.

        Zero would read as "it was wrong about everything", which is a
        measurement. Absent is the honest value.
        """
        result = self._measure(self._output(self._all_true_findings()))

        self.assertIsNone(result.precision)
        self.assertIsNone(result.recall)
        self.assertEqual(result.evidence_backed_share, 0.0)

    def test_a_correct_report_of_no_defects_is_not_scored_as_a_miss(self):
        result = self._measure(self._output([]))

        self.assertEqual(result.missed_defects, [])
        self.assertIsNone(result.recall)


class TestAnEmptyResultIsNotACleanBillOfHealth(_Fixture):
    """The metric that is easy to leave out.

    Asserting nothing is the right answer to "did your claims hold": there
    were none. It is not an answer to "is this repository sound", and the two
    look identical in a run document that reports `passed` at a full score.
    """

    root = WITH_DEFECTS

    def test_an_empty_review_passes_and_the_measurement_says_so(self):
        result = self._measure(self._output([]))

        self.assertTrue(result.passed)
        self.assertEqual(result.asserted, 0)
        self.assertTrue(result.overstates_completeness)

    def test_it_is_scored_as_having_missed_every_known_defect(self):
        """Three real defects sat in the files it read, and it reported none."""
        result = self._measure(self._output([]))

        self.assertEqual(sorted(result.missed_defects), ["D1", "D2", "D3"])
        self.assertEqual(result.recall, 0.0)
        self.assertIsNone(result.precision)

    def test_a_run_that_did_assert_something_does_not_raise_the_flag(self):
        """Negative control: the flag is about silence, not about failing."""
        result = self._measure(self._output(self._all_true_findings()))

        self.assertTrue(result.passed)
        self.assertFalse(result.overstates_completeness)

    def test_the_text_a_human_reads_no_longer_implies_a_clean_repo(self):
        """Measuring it is not enough if the run still reads as a verdict.

        Before this, the trailer for an empty review was `Stop reason: passed`,
        `Criteria met: 1.0`, `Status: passed`, and nothing else. Every word of
        that is true and the impression it leaves is not.
        """
        self._measure(self._output([]))
        trailer = render_run_text(self.run_document).split("---", 1)[1]

        self.assertIn("asserted no finding", trailer)
        self.assertIn("not a statement that", trailer)


class TestTheTrailerWarningBelongsToReviews(unittest.TestCase):
    """The warning is about silence where findings were owed.

    A route that answers a question makes no findings by design. Telling its
    reader that nothing was established about the sources would answer a
    question nobody asked — there are no sources.
    """

    def test_a_plain_answer_does_not_get_the_review_warning(self):
        run = AtlasController(max_iterations=1).run("hej", json_mode=True)
        evaluation = run["evaluations"][-1]

        # The preconditions that made it fire: it passed, and it graded no
        # claim. Only the route's contract tells this case from a review's.
        self.assertTrue(evaluation["passed"])
        self.assertEqual(evaluation["citation_checks"], [])
        self.assertEqual(run["plan"]["route_name"], "general")
        self.assertNotIn(
            "claims_are_settled",
            evaluation["met_criteria"] + evaluation["unmet_criteria"],
        )

        self.assertNotIn("asserted no finding", render_run_text(run))


class TestSilenceIsWorthWhatTheTaskAsked(_Fixture):
    """The same empty review, measured under both kinds of task.

    `TestAnEmptyResultIsNotACleanBillOfHealth` measures silence under a task
    the plan could not narrow, and there it still passes: there is no question
    to have left unanswered, so only the route's criteria apply and an output
    with no claims meets all of them. Under a narrowed task the gate closes.

    Both rows belong in the published results. Reporting only the first would
    have `docs/benchmark.md` say an empty review passes, full stop, which
    stopped being true for a narrowed task when `findings_are_on_topic`
    landed — and a benchmark has to describe the code it actually runs.
    """

    root = WITH_DEFECTS

    def test_the_broad_task_is_the_one_that_cannot_be_narrowed(self):
        """Stated rather than assumed: this is why the rows differ."""
        self._measure(self._output([]))

        self.assertEqual(self.run_document["plan"]["review"]["topic"], "unknown")

    def test_an_empty_review_no_longer_passes_a_narrowed_task(self):
        result = self._measure_narrowed(self._output([]))
        evaluation = self.run_document["evaluations"][-1]

        self.assertEqual(self.run_document["plan"]["review"]["topic"], "secrets")
        self.assertFalse(result.passed)
        self.assertIn("findings_are_on_topic", evaluation["unmet_criteria"])
        # Still measured as a miss, and now also stopped. The flag is about
        # what the run asserted, not about whether it passed.
        self.assertEqual(result.recall, 0.0)

    def test_the_committed_password_still_passes_under_the_same_task(self):
        """Negative control: the narrowed task is not simply harder to pass.

        One settled claim about the source the question named, and the run is
        done — the same defect `D3` the broad task scores.
        """
        finding = self._finding("settings.env", ClaimKind.CONTAINS, "PASSWORD=admin")
        result = self._measure_narrowed(self._output([finding]))

        self.assertTrue(result.passed)
        self.assertEqual(result.found_defects, ["D3"])
        self.assertFalse(result.overstates_completeness)


class TestTheWholeChainFromNoObservations(_Fixture):
    """Nothing read, a question asked, and a defect established from the read.

    The measurements above hand the run its observations. That is the right
    shape for measuring the gate, and it skips the half of the loop that
    decides *what to read* — so on its own it would let a regression in the
    reading path through with every published number unchanged.
    """

    root = WITH_DEFECTS

    def test_a_defect_is_established_from_a_read_the_plan_asked_for(self):
        finding = self._finding("settings.env", ClaimKind.CONTAINS, "PASSWORD=admin")
        result = self._measure_from_nothing(self._output([finding]))
        run = self.run_document

        # 1. It really did start with nothing, and said so.
        first = run["evaluations"][0]
        self.assertIn("plan_targets_read", first["unmet_criteria"])
        self.assertEqual(first["next_action"]["kind"], "observe_again")
        self.assertEqual(first["next_action"]["actor"], "host")

        # 2. The host read what the question pointed at.
        rounds = run["metadata"]["observation_rounds"]
        self.assertIn(
            "settings.env",
            [added["path"] for entry in rounds for added in entry["added"]],
        )

        # 3. And the defect was established against those bytes.
        self.assertTrue(result.passed)
        self.assertEqual(result.found_defects, ["D3"])
        self.assertEqual(result.precision, 1.0)
        self.assertEqual(result.evidence_backed_share, 1.0)

    def test_the_same_chain_with_nothing_to_say_stops_instead(self):
        """The other half: the read happens, and the answer still says nothing."""
        result = self._measure_from_nothing(self._output([]))
        evaluation = self.run_document["evaluations"][-1]

        self.assertFalse(result.passed)
        self.assertIn("findings_are_on_topic", evaluation["unmet_criteria"])
        self.assertEqual(result.recall, 0.0)


class TestPrecisionCountsFindingsNotDistinctDefects(_Fixture):
    """A run that states one real defect twice is not half wrong.

    `found_defects` is deduplicated, because recall is a share of the defects
    and a defect found twice is one defect found. Precision is a share of what
    the run *established*, so its numerator has to count findings too. Dividing
    distinct ids by a count of findings mixed the two.
    """

    root = WITH_DEFECTS

    def test_the_same_defect_claimed_twice_is_still_fully_precise(self):
        finding = self._finding("settings.env", ClaimKind.CONTAINS, "PASSWORD=admin")
        result = self._measure(self._output([finding, dict(finding)]))

        self.assertEqual(result.verified, 2)
        self.assertEqual(result.found_defects, ["D3"])
        self.assertEqual(result.verified_non_defects, 0)
        self.assertEqual(result.precision, 1.0)
        # Recall is unmoved: two findings, one defect, three in the key.
        self.assertEqual(result.recall, 0.33)

    def test_every_established_finding_is_a_hit_or_noise_and_never_both(self):
        """The invariant behind the share, asserted rather than assumed."""
        findings = self._all_true_findings()
        findings.append(self._finding("README.md", ClaimKind.CONTAINS, "# Demorepo"))
        findings.append(dict(findings[0]))
        result = self._measure(self._output(findings))

        hits = round(result.precision * result.verified)
        self.assertEqual(hits + result.verified_non_defects, result.verified)
        self.assertEqual(result.verified, 5)
        self.assertEqual(result.verified_non_defects, 1)
        self.assertEqual(result.precision, 0.8)


class TestTheAnswerKeyItself(unittest.TestCase):
    def test_both_fixtures_declare_the_same_files(self):
        """The repos differ in content, not in shape, so the defect is the
        variable rather than the file list."""
        names = {
            path.name
            for path in WITH_DEFECTS.iterdir()
            if path.name != "ground_truth.json"
        }
        other = {
            path.name
            for path in WITHOUT_DEFECTS.iterdir()
            if path.name != "ground_truth.json"
        }

        self.assertEqual(names, other)

    def test_every_declared_defect_is_actually_present(self):
        """An answer key nobody checked is a second opinion, not a key."""
        truth = GroundTruth.load(WITH_DEFECTS / "ground_truth.json")

        self.assertTrue(truth.defects)
        for defect in truth.defects:
            with self.subTest(defect.id):
                content = (WITH_DEFECTS / defect.path).read_text(encoding="utf-8")
                if defect.kind == "source_contains_literal":
                    self.assertIn(defect.text, content)
                else:
                    self.assertNotIn(defect.text, content)

    def test_none_of_them_is_present_in_the_clean_repo(self):
        truth = GroundTruth.load(WITH_DEFECTS / "ground_truth.json")

        for defect in truth.defects:
            with self.subTest(defect.id):
                content = (WITHOUT_DEFECTS / defect.path).read_text(encoding="utf-8")
                if defect.kind == "source_contains_literal":
                    self.assertNotIn(defect.text, content)
                else:
                    self.assertIn(defect.text, content)

    def test_the_clean_repo_declares_no_defects(self):
        truth = GroundTruth.load(WITHOUT_DEFECTS / "ground_truth.json")

        self.assertEqual(truth.defects, [])


if __name__ == "__main__":
    unittest.main()
