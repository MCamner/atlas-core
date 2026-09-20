"""P0.2: the bridge between observations and evaluation.

ROADMAP.md P0.2. Before this, a run carried `list[str]` and the evaluator
graded a finding by checking whether a filename appeared in its text. A false
claim about a file that was genuinely read passed at 0.9, and
`test_a_false_finding_with_a_broken_citation_cannot_pass` is the end-to-end
proof that it no longer does.

The limit this suite is careful about: the gate is citation *integrity*. An
intact citation can still back a false claim — `test_a_sound_citation_still_does
_not_mean_verified` asserts exactly that, so nobody reads a green run as a
verified one. Deciding whether a source supports a claim is P0.2b.
"""

import json
import shutil
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from atlas_core import AtlasController, StubModelAdapter
from atlas_core.evaluator import evaluate
from atlas_core.evidence import FINDINGS_FENCE, structured_findings
from atlas_core.evidence_base import EvidenceBase
from atlas_core.observation import Observation
from atlas_core.snapshot import collect_observation, take_snapshot

README = "# Atlas Core\n\npip install atlas-core\n\nEn avgränsad loop-motor.\n"

# Long enough to clear the substance threshold, and carrying every section the
# formatting check wants. The point of these tests is what happens when the
# form is perfect and the substance is not.
PROSE = """# Repogranskning

Granskningen nedan bygger på de källor som lästes denna körning och går igenom
repots dokumentation, testupplägg och släppprocess i tillräcklig detalj för att
motivera de slutsatser som dras. Texten är avsiktligt lång nog för att passera
substanskravet, eftersom poängen är att visa vad som släpps igenom när formen
är korrekt men sakinnehållet inte är kontrollerat mot källan.

## Observed sources
- `README.md`

## Verified findings
- {claim}

## Recommendation
Lägg till ett installationsavsnitt.

## Next step
Skriv avsnittet.

## Confidence
Hög.
"""

FALSE_CLAIM = "README.md saknar helt installationsinstruktioner och nämner aldrig Python."


class _Loop(unittest.TestCase):
    """A real snapshot, one real observation, and a model that says what we tell it."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        (self.root / "README.md").write_text(README, encoding="utf-8")
        self.snapshot = take_snapshot(self.root)
        self.observation = collect_observation(self.snapshot, "README.md")
        self.base = EvidenceBase(snapshot=self.snapshot, observations=[self.observation])
        # Prose context as well, so every test runs with both channels present
        # and the strict path is chosen by what the run carries, not by absence.
        self.context = [f"README.md:\n{README}"]

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _citation(self, **overrides):
        fields = {
            "source_id": self.observation.source_id,
            "content_sha256": self.observation.content_sha256,
            "line_start": 1,
            "line_end": 1,
            "quoted": "# Atlas Core",
        }
        fields.update(overrides)
        return fields

    def _output(self, claim=FALSE_CLAIM, citations=None, block=True):
        text = PROSE.format(claim=claim)
        if not block:
            return text
        findings = [
            {
                "claim": claim,
                "scope": "README.md",
                "severity": "P1",
                "severity_rationale": "Blockerar en ny användare.",
                "evidence": citations if citations is not None else [self._citation()],
            }
        ]
        return f"{text}\n```{FINDINGS_FENCE}\n{json.dumps(findings)}\n```\n"

    def _run(self, output, *, evidence=True, max_iterations=1):
        controller = AtlasController(
            max_iterations=max_iterations, model_adapter=StubModelAdapter(output)
        )
        return controller.run(
            "granska repo",
            observations=self.context,
            evidence=self.base if evidence else None,
            json_mode=True,
        )


class TestTheGateEndToEnd(_Loop):
    """Requirement 4: the controller, not just the evaluator."""

    def test_a_false_finding_with_a_broken_citation_cannot_pass(self):
        """The whole point of the PR, asserted through the public entry point.

        Everything the older checks look at is correct here: all sections
        present, an `## Observed sources` heading, and a finding whose text
        names a file that really was read. Only the citation is wrong.
        """
        run = self._run(self._output(citations=[self._citation(quoted="FEL CITAT")]))
        evaluation = run["evaluations"][-1]

        self.assertFalse(evaluation["passed"])
        self.assertNotEqual(run["stop_reason"], "passed")
        self.assertIn("unsound_citations", evaluation["evidence_gaps"])
        self.assertIn(FALSE_CLAIM, evaluation["unverified_claims"])

    def test_the_older_checks_would_have_accepted_the_same_answer(self):
        """What the gate is worth. Without an evidence base this passes at 0.9."""
        run = self._run(
            self._output(citations=[self._citation(quoted="FEL CITAT")]), evidence=False
        )
        evaluation = run["evaluations"][-1]

        self.assertTrue(evaluation["passed"])
        self.assertEqual(run["stop_reason"], "passed")
        self.assertEqual(evaluation["evidence_gaps"], [])

    def test_a_finding_with_no_machine_readable_citation_cannot_pass(self):
        """Prose alone is not checkable, however well it is written."""
        run = self._run(self._output(block=False))
        evaluation = run["evaluations"][-1]

        self.assertFalse(evaluation["passed"])
        self.assertIn("uncheckable_findings", evaluation["evidence_gaps"])
        self.assertIn(FALSE_CLAIM, evaluation["unverified_claims"])

    def test_the_score_itself_drops_below_the_threshold(self):
        """The gate is arithmetic as well as boolean, so neither alone carries it."""
        blocked = self._run(self._output(citations=[self._citation(quoted="FEL")]))
        accepted = self._run(self._output())

        self.assertLess(blocked["evaluations"][-1]["quality_score"], 0.78)
        self.assertGreaterEqual(accepted["evaluations"][-1]["quality_score"], 0.78)


class TestWhatCannotContributeToPass(_Loop):
    """Requirement 3, case by case."""

    def test_an_unknown_source_id_cannot_contribute(self):
        run = self._run(self._output(citations=[self._citation(source_id="0" * 16)]))
        evaluation = run["evaluations"][-1]

        self.assertFalse(evaluation["passed"])
        self.assertEqual(
            evaluation["citation_checks"][0]["statuses"][0]["status"], "unknown_source"
        )

    def test_a_tampered_excerpt_cannot_contribute(self):
        """The observation lies about its own line range; the file is untouched."""
        lying = replace(self.observation, excerpt="HELT PÅHITTAT")
        base = EvidenceBase(snapshot=self.snapshot, observations=[lying])
        evaluation = evaluate(
            "granska repo",
            self._output(),
            [],
            1,
            1,
            route_name="repo_review",
            observations=self.context,
            evidence_base=base,
        )

        self.assertFalse(evaluation.passed)
        self.assertEqual(
            evaluation.citation_checks[0]["statuses"][0]["status"], "excerpt_mismatch"
        )

    def test_a_changed_file_cannot_contribute(self):
        (self.root / "README.md").write_text(README + "ändrad\n", encoding="utf-8")

        run = self._run(self._output())
        evaluation = run["evaluations"][-1]

        self.assertFalse(evaluation["passed"])
        self.assertEqual(
            evaluation["citation_checks"][0]["statuses"][0]["status"], "stale_source"
        )

    def test_a_missing_observation_cannot_contribute(self):
        """An evidence base that holds nothing supports nothing."""
        empty = EvidenceBase(snapshot=self.snapshot, observations=[])
        evaluation = evaluate(
            "granska repo",
            self._output(),
            [],
            1,
            1,
            route_name="repo_review",
            observations=self.context,
            evidence_base=empty,
        )

        self.assertFalse(evaluation.passed)
        self.assertEqual(evaluation.evidence_gaps, ["no_sources_observed"])

    def test_a_malformed_findings_block_cannot_contribute(self):
        """Unreadable is reported, never silently treated as "asserts nothing"."""
        broken = PROSE.format(claim=FALSE_CLAIM) + f"\n```{FINDINGS_FENCE}\n[{{nope}}]\n```\n"

        run = self._run(broken)
        evaluation = run["evaluations"][-1]

        self.assertFalse(evaluation["passed"])
        self.assertIn("malformed_findings", evaluation["evidence_gaps"])


class TestSoundIsNotVerified(_Loop):
    """The limit this PR does not move, asserted so nobody assumes otherwise."""

    def test_a_sound_citation_still_does_not_mean_verified(self):
        """The claim below is false, and its citation is perfectly sound.

        It quotes line 1 of a README that does contain installation
        instructions. The gate lets it through because citation integrity is
        all it checks — closing this is P0.2b, and the run record must not
        pretend otherwise.
        """
        run = self._run(self._output())
        evaluation = run["evaluations"][-1]

        self.assertTrue(evaluation["passed"])
        record = evaluation["citation_checks"][0]
        self.assertTrue(record["citations_are_sound"])
        self.assertEqual(record["verdict"], "insufficient_evidence")
        self.assertNotEqual(record["verdict"], "verified")

    def test_the_reason_says_eligible_not_confirmed(self):
        run = self._run(self._output())
        reasons = " ".join(run["evaluations"][-1]["reasons"])

        self.assertIn("eligible for semantic verification", reasons)
        self.assertNotIn("verified that", reasons)


class TestActionableOrStop(_Loop):
    """Requirement 3's second half: return a gap to fix, or stop."""

    def test_a_miscited_finding_is_worth_another_pass(self):
        """A wrong quote can be rewritten from sources the run already holds."""
        evaluation = evaluate(
            "granska repo",
            self._output(citations=[self._citation(quoted="FEL")]),
            [],
            1,
            2,
            route_name="repo_review",
            observations=self.context,
            evidence_base=self.base,
        )

        self.assertTrue(evaluation.should_retry)
        self.assertIsNotNone(evaluation.suggested_adjustment)
        self.assertIn("quote_mismatch", evaluation.suggested_adjustment or "")

    def test_a_stale_source_stops_instead_of_burning_an_iteration(self):
        """Re-wording cannot fix a file that moved; that needs a new snapshot."""
        (self.root / "README.md").write_text(README + "ändrad\n", encoding="utf-8")

        evaluation = evaluate(
            "granska repo",
            self._output(),
            [],
            1,
            2,
            route_name="repo_review",
            observations=self.context,
            evidence_base=self.base,
        )

        self.assertFalse(evaluation.should_retry)
        self.assertIsNone(evaluation.suggested_adjustment)

    def test_the_adjustment_names_the_available_source_ids(self):
        evaluation = evaluate(
            "granska repo",
            self._output(block=False),
            [],
            1,
            2,
            route_name="repo_review",
            observations=self.context,
            evidence_base=self.base,
        )

        self.assertIn(self.observation.source_id, evaluation.suggested_adjustment or "")


class TestBackwardsCompatibilityIsExplicit(_Loop):
    """Requirement 1: no silent conversion in either direction."""

    def test_a_run_without_an_evidence_base_is_graded_exactly_as_before(self):
        run = self._run(self._output(block=False), evidence=False)

        self.assertTrue(run["evaluations"][-1]["passed"])
        self.assertEqual(run["evaluations"][-1]["evidence_coverage"], 1.0)

    def test_the_run_record_says_which_path_ran(self):
        """A reader must be able to tell a checked run from an unchecked one."""
        checked = self._run(self._output())
        unchecked = self._run(self._output(), evidence=False)

        self.assertIsNotNone(checked["evidence_base"])
        self.assertIsNone(unchecked["evidence_base"])
        self.assertTrue(checked["evaluations"][-1]["citation_checks"])
        self.assertEqual(unchecked["evaluations"][-1]["citation_checks"], [])

    def test_prose_observations_are_never_turned_into_evidence(self):
        """There is no such conversion, and there must not be one.

        A function that built an `Observation` from a formatted string would
        have to invent a digest and a snapshot, producing a source that claims
        to be verifiable while nothing behind it was read.
        """
        import atlas_core.evidence_base as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        for forbidden in ("Observation.create", "Observation("):
            self.assertNotIn(
                forbidden,
                source,
                "evidence_base must not construct observations from prose",
            )

    def test_the_prose_channel_still_reaches_the_executor(self):
        run = self._run(self._output())

        self.assertEqual(run["observations"], self.context)


class TestTheEvidenceBaseItself(_Loop):
    def _from_another_snapshot(self) -> Observation:
        """A valid observation that simply belongs to a different state.

        Built through `create`, not `replace`: the P0.1a guard derives
        `source_id` from the snapshot, so re-pointing one is already refused
        one layer down. What `EvidenceBase` has to catch is the *consistent*
        foreign observation, which is the one that would otherwise slip in.
        """
        return Observation.create(
            source_type="local_file",
            path="README.md",
            collected_at=self.observation.collected_at,
            content_sha256=self.observation.content_sha256,
            excerpt=self.observation.excerpt,
            line_start=self.observation.line_start,
            line_end=self.observation.line_end,
            snapshot_id="0" * 16,
        )

    def test_an_observation_from_another_snapshot_is_refused(self):
        other = self._from_another_snapshot()

        with self.assertRaises(ValueError) as raised:
            EvidenceBase(snapshot=self.snapshot, observations=[other])

        self.assertIn("mixes states", str(raised.exception))

    def test_a_duplicate_source_id_is_refused(self):
        with self.assertRaises(ValueError):
            EvidenceBase(
                snapshot=self.snapshot,
                observations=[self.observation, self.observation],
            )

    def test_validation_survives_replace(self):
        """In `__post_init__`, so it cannot be stepped around."""
        other = self._from_another_snapshot()

        with self.assertRaises(ValueError):
            replace(self.base, observations=[other])

    def test_the_root_is_the_snapshots_not_a_callers(self):
        self.assertEqual(self.base.root, Path(self.snapshot.root))


class TestTheFindingsBlock(unittest.TestCase):
    def test_an_absent_block_is_not_a_malformed_one(self):
        parsed = structured_findings("no block here")

        self.assertFalse(parsed.present)
        self.assertIsNone(parsed.malformed)

    def test_a_block_that_is_not_a_list_is_malformed(self):
        parsed = structured_findings(f'```{FINDINGS_FENCE}\n{{"claim": "x"}}\n```')

        self.assertIn("list of findings", parsed.malformed or "")

    def test_a_bad_digest_is_refused_at_parse_time(self):
        payload = json.dumps(
            [
                {
                    "claim": "x",
                    "scope": "y",
                    "severity_rationale": "r",
                    "evidence": [
                        {
                            "source_id": "a",
                            "content_sha256": "inte en digest",
                            "line_start": 1,
                            "line_end": 1,
                            "quoted": "q",
                        }
                    ],
                }
            ]
        )
        parsed = structured_findings(f"```{FINDINGS_FENCE}\n{payload}\n```")

        self.assertIn("64 lowercase hex", parsed.malformed or "")

    def test_other_json_in_the_output_is_not_mistaken_for_findings(self):
        parsed = structured_findings('```json\n[{"claim": "x"}]\n```')

        self.assertFalse(parsed.present)


if __name__ == "__main__":
    unittest.main()
