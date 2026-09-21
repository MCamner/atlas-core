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
from typing import Any

from atlas_core import AtlasController, StubModelAdapter
from atlas_core.evaluator import evaluate
from atlas_core.evidence import FINDINGS_FENCE, structured_findings
from atlas_core.evidence_base import EvidenceBase
from atlas_core.observation import Observation
from atlas_core.redaction import redact_text
from atlas_core.snapshot import collect_observation, take_snapshot

README = (
    "# Atlas Core\n\npip install atlas-core\n\nEn avgränsad loop-motor.\n"
    # Planted so the export tests can assert their absence rather than assert
    # that a clean file stays clean, which would prove nothing.
    "Kontakt: privat@example.com\n"
    "Token: ghp_abcdefghijklmnopqrstuvwxyzABCDEF0123\n"
)

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

#: Distinguishes "caller said nothing" from "caller said no condition".
_DEFAULT: Any = object()


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

    def _condition(self, **overrides):
        """A condition the README genuinely satisfies, unless overridden.

        A condition alone cannot pass since P0.2b — its relevance to the claim
        is unchecked. `_passing_finding` is what a finding that may pass looks
        like.
        """
        fields = {
            "kind": "absent",
            "source_id": self.observation.source_id,
            "text": "detta finns inte i filen",
        }
        fields.update(overrides)
        return fields

    def _passing_finding(self):
        """A finding that may reach PASS: a typed claim, stated as it reads.

        The claim text is derived rather than written, which is the property
        that closes the gap between what is asserted and what is settled.
        """
        from atlas_core.claim_check import ClaimKind, TypedClaim

        typed = TypedClaim(
            kind=ClaimKind.CONTAINS,
            source_id=self.observation.source_id,
            text="pip install",
        )
        claim = typed.render(
            self.observation.path,
            self.observation.line_start,
            self.observation.line_end,
        )
        return {
            "claim": claim,
            "scope": "README.md",
            "severity": "P1",
            "severity_rationale": "Blockerar en ny användare.",
            "evidence": [self._citation()],
            "typed_claim": {
                "kind": typed.kind.value,
                "source_id": typed.source_id,
                "text": typed.text,
            },
        }

    def _passing_output(self):
        return self._block(PROSE.format(claim=self._passing_finding()["claim"]),
                           [self._passing_finding()])

    def _output(
        self,
        claim: str = FALSE_CLAIM,
        citations: list[dict[str, object]] | None = None,
        block: bool = True,
        condition: dict[str, object] | None | Any = _DEFAULT,
    ) -> str:
        text = PROSE.format(claim=claim)
        if not block:
            return text
        finding: dict[str, Any] = {
            "claim": claim,
            "scope": "README.md",
            "severity": "P1",
            "severity_rationale": "Blockerar en ny användare.",
            "evidence": citations if citations is not None else [self._citation()],
        }
        # The default declares a condition, because since P0.2b a finding
        # without one cannot pass and most tests here are about other things.
        if condition is _DEFAULT:
            finding["claim_check"] = self._condition()
        elif condition is not None:
            finding["claim_check"] = condition
        return self._block(text, [finding])

    def _block(self, text, findings):
        """Attach a findings block to prose."""
        fence = "```" + FINDINGS_FENCE
        return text + "\n" + fence + "\n" + json.dumps(findings) + "\n```\n"

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

    def test_the_unmet_criterion_is_named_rather_than_priced(self):
        """Was: the score drops below a threshold.

        P1.1 box three replaced the arithmetic gate with named criteria, so
        the thing to assert is *which* requirement went unmet — a number that
        fell short said the run was short of something without saying of what.
        The score still moves, and it reports rather than decides.
        """
        blocked = self._run(self._output(citations=[self._citation(quoted="FEL")]))
        accepted = self._run(self._passing_output())

        self.assertIn("citations_hold", blocked["evaluations"][-1]["unmet_criteria"])
        self.assertEqual(accepted["evaluations"][-1]["unmet_criteria"], [])
        self.assertLess(
            blocked["evaluations"][-1]["quality_score"],
            accepted["evaluations"][-1]["quality_score"],
        )


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


class TestSoundIsNotEnough(_Loop):
    """What used to be this suite's stated limit, now closed by P0.2b.

    Before the claim check, a sound citation was all `repo_review` required, so
    a false claim quoting line 1 of a README correctly passed at 0.9. These
    tests hold that door shut.
    """

    def test_a_sound_citation_alone_no_longer_passes(self):
        run = self._run(self._output(condition=None))
        evaluation = run["evaluations"][-1]
        record = evaluation["citation_checks"][0]

        self.assertTrue(record["citations_are_sound"])
        self.assertFalse(evaluation["passed"])
        self.assertIn("unverified_findings", evaluation["evidence_gaps"])
        self.assertEqual(record["verdict"], "insufficient_evidence")

    def test_the_run_says_the_claim_itself_was_not_checked(self):
        run = self._run(self._output(condition=None))
        record = run["evaluations"][-1]["citation_checks"][0]

        self.assertEqual(record["claim_check"]["result"], "not_declared")
        self.assertNotEqual(record["verification_method"], "semantic")

    def test_a_condition_that_holds_is_still_not_a_confirmed_claim(self):
        """A settled condition beside free text decides nothing.

        This is the case the review caught: the condition holds, and the claim
        it sits beside is false. Naming the result `condition_supported` is
        what keeps the two apart.
        """
        run = self._run(self._output())
        evaluation = run["evaluations"][-1]
        record = evaluation["citation_checks"][0]

        self.assertEqual(record["claim_check"]["result"], "condition_supported")
        self.assertFalse(record["claim_check"]["is_decisive"])
        self.assertEqual(record["verdict"], "insufficient_evidence")
        self.assertFalse(evaluation["passed"])

    def test_a_typed_claim_is_what_it_takes_to_pass(self):
        """Negative control: the gate is not shut for everything."""
        run = self._run(self._passing_output())
        evaluation = run["evaluations"][-1]

        self.assertTrue(evaluation["passed"])
        self.assertEqual(evaluation["citation_checks"][0]["verdict"], "verified")
        self.assertIn("The claim is the predicate", " ".join(evaluation["reasons"]))


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

        self.assertIsNotNone(checked["evidence_manifest"])
        self.assertIsNone(unchecked["evidence_manifest"])
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
        """Unchanged as a channel; masked on the way out.

        The export now redacts the whole document, so the exported list is the
        given context with credentials and personal data masked — not a
        different set of observations.
        """
        run = self._run(self._output())

        self.assertEqual(
            run["observations"], [redact_text(item) for item in self.context]
        )
        self.assertEqual(len(run["observations"]), len(self.context))


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


class TestTheExportIsSanitised(_Loop):
    """Review blocker 1: `to_dict()` walked straight into the raw base.

    `asdict` recurses, so every excerpt the run read and the absolute path it
    read from were published in the run document — the sanitised manifest from
    P0.1c existed and was not used. These tests assert absence of things the
    fixture genuinely plants, so a pass cannot come from a clean input.
    """

    def _manifest(self):
        run = self._run(self._output())
        self.assertIsNotNone(run["evidence_manifest"])
        return run, json.dumps(run["evidence_manifest"], ensure_ascii=False)

    def test_the_absolute_root_is_not_exported(self):
        """Dropped, not masked: redaction cannot recognise an arbitrary path."""
        run, document = self._manifest()

        self.assertNotIn("root", run["evidence_manifest"]["snapshot"])
        self.assertNotIn(str(self.root), document)

    def test_secrets_in_an_excerpt_do_not_reach_the_export(self):
        _, document = self._manifest()

        self.assertIn("privat@example.com", README)
        self.assertNotIn("privat@example.com", document)
        self.assertNotIn("ghp_abcdefghijklmnopqrstuvwxyzABCDEF0123", document)

    def test_the_whole_run_document_is_free_of_the_raw_base(self):
        """Not only the manifest: nothing else may carry it either."""
        run = self._run(self._output())
        document = json.dumps(run, ensure_ascii=False)

        self.assertNotIn("evidence_base", document)
        self.assertNotIn(str(self.root), document)
        self.assertNotIn("ghp_abcdefghijklmnopqrstuvwxyzABCDEF0123", document)

    def test_the_prose_channel_is_masked_as_well(self):
        """The hole this closes. It used to export verbatim.

        The sanitised manifest covered the evidence channel only, so an adapter
        that put file contents into `observations` published the same secret
        one key away from a masked manifest. Masking is now applied to the
        assembled run document, which covers every channel including this one.
        """
        run = self._run(self._output())
        exported = json.dumps(run["observations"])

        self.assertNotIn("privat@example.com", exported)
        self.assertNotIn("ghp_abcdefghijklmnopqrstuvwxyzABCDEF0123", exported)

    def test_the_digest_survives_so_the_manifest_still_points_somewhere(self):
        """Negative control: redaction must not mask the verification pointer."""
        run, _ = self._manifest()
        entry = run["evidence_manifest"]["observations"][0]

        self.assertEqual(entry["content_sha256"], self.observation.content_sha256)
        self.assertEqual(entry["source_id"], self.observation.source_id)

    def test_the_manifest_claims_no_verification_of_its_own(self):
        """Exporting is not verifying; what was checked is in citation_checks."""
        run, _ = self._manifest()
        entry = run["evidence_manifest"]["observations"][0]

        self.assertEqual(entry["verification"], "unknown")
        self.assertFalse(entry["is_evidence"])
        self.assertTrue(run["evaluations"][-1]["citation_checks"][0]["citations_are_sound"])


class TestOneBlockingGapStopsTheRetry(_Loop):
    """Review blocker 2: a fixable finding made a doomed retry look worth it.

    A retry re-runs the producer once for the whole output. If one finding
    needs a fresh observation, the pass that fixes the citable ones still comes
    back with that one unchanged — so the iteration is spent to fail on the
    same ground.
    """

    def _mixed(self, max_iterations=2):
        """One finding gone stale, one bullet with no citation at all."""
        (self.root / "README.md").write_text(README + "ändrad\n", encoding="utf-8")
        text = PROSE.format(claim=FALSE_CLAIM).replace(
            f"- {FALSE_CLAIM}", f"- {FALSE_CLAIM}\n- Ett fynd helt utan citat."
        )
        findings = [
            {
                "claim": FALSE_CLAIM,
                "scope": "README.md",
                "severity": "P1",
                "severity_rationale": "r",
                "evidence": [self._citation()],
            }
        ]
        output = self._block(text, findings)
        return self._run(output, max_iterations=max_iterations)

    def test_a_stale_source_blocks_the_retry_even_beside_a_citable_finding(self):
        run = self._mixed()
        evaluation = run["evaluations"][0]

        self.assertIn("uncheckable_findings", evaluation["evidence_gaps"])
        self.assertEqual(
            [s["status"] for r in evaluation["citation_checks"] for s in r["statuses"]],
            ["stale_source"],
        )
        self.assertFalse(evaluation["should_retry"])

    def test_no_iteration_is_spent_on_it(self):
        run = self._mixed()

        self.assertEqual(run["iteration"], 1)
        self.assertEqual(run["stop_reason"], "blocked")

    def test_a_moved_source_is_not_reported_as_a_verdict_on_the_answer(self):
        """`blocked` asks for a fresh observation; `insufficient_evidence`
        asks for a better answer. Sharing one name sent readers the wrong way."""
        run = self._mixed()

        self.assertEqual(run["evaluations"][0]["blocked_by"], ["stale_source"])
        self.assertNotEqual(run["stop_reason"], "insufficient_evidence")

    def test_the_run_says_why_it_did_not_try_again(self):
        """"The loop gave up" and "observe again" need different actions."""
        run = self._mixed()
        missing = " ".join(run["evaluations"][0]["missing"])

        self.assertIn("stale_source", missing)
        self.assertIn("observed again", missing)

    def test_an_uncited_finding_alone_is_still_worth_a_retry(self):
        """Negative control: the fix must not block every retry."""
        run = self._run(self._output(block=False), max_iterations=2)

        self.assertTrue(run["evaluations"][0]["should_retry"])
        self.assertEqual(run["iteration"], 2)

    def test_a_miscited_finding_beside_an_uncited_one_is_still_worth_a_retry(self):
        """Both gaps present, neither blocking: the retry must survive."""
        text = PROSE.format(claim=FALSE_CLAIM).replace(
            f"- {FALSE_CLAIM}", f"- {FALSE_CLAIM}\n- Ett fynd helt utan citat."
        )
        findings = [
            {
                "claim": FALSE_CLAIM,
                "scope": "README.md",
                "severity": "P1",
                "severity_rationale": "r",
                "evidence": [self._citation(quoted="FEL CITAT")],
            }
        ]
        run = self._run(self._block(text, findings), max_iterations=2)
        evaluation = run["evaluations"][0]

        self.assertEqual(
            sorted(evaluation["evidence_gaps"]),
            ["uncheckable_findings", "unsound_citations"],
        )
        self.assertTrue(evaluation["should_retry"])


class TestACitationCanBeFollowedToItsExcerpt(_Loop):
    """P0.1 box three: finding → `source_id` **and the exact excerpt**.

    The run document already named the source per citation, which is half the
    link. The other half is the text the claim actually rests on: without it a
    reader has the id of a file and no way to see which lines were relied on
    short of re-reading the file and guessing. The manifest holds the source;
    the citation record has to hold the span.
    """

    def _statuses(self, run):
        return run["evaluations"][-1]["citation_checks"][0]["statuses"]

    def test_a_citation_records_the_lines_it_relied_on(self):
        run = self._run(self._passing_output())
        citation = self._statuses(run)[0]

        self.assertEqual(citation["source_id"], self.observation.source_id)
        self.assertEqual(citation["line_start"], 1)
        self.assertEqual(citation["line_end"], 1)
        self.assertEqual(citation["quoted"], "# Atlas Core")
        self.assertEqual(citation["status"], "intact")

    def test_the_source_id_resolves_in_the_manifest_of_the_same_run(self):
        """The link is only worth something if both ends are in one document."""
        run = self._run(self._passing_output())
        source_id = self._statuses(run)[0]["source_id"]

        entry = {
            item["source_id"]: item for item in run["evidence_manifest"]["observations"]
        }[source_id]

        self.assertEqual(entry["path"], "README.md")
        self.assertEqual(entry["content_sha256"], self.observation.content_sha256)

    def test_each_citation_keeps_its_own_span_when_a_finding_cites_several(self):
        """Two citations, and the broken one must not borrow the other's span."""
        good = self._citation()
        wrong_line = self._citation(line_start=3, line_end=3, quoted="# Atlas Core")
        run = self._run(self._output(citations=[good, wrong_line]))

        first, second = self._statuses(run)

        self.assertEqual(first["status"], "intact")
        self.assertEqual((first["line_start"], first["line_end"]), (1, 1))
        self.assertEqual(second["status"], "quote_mismatch")
        self.assertEqual((second["line_start"], second["line_end"]), (3, 3))

    def test_a_quoted_span_is_masked_on_the_way_out(self):
        """Bounded and sanitised, like the manifest excerpt beside it.

        The quote is a slice of a real file, so it can carry a credential just
        as an excerpt can. It is exported through the same masking.
        """
        citation = self._citation(line_start=7, line_end=7, quoted=README.splitlines()[6])
        run = self._run(self._output(citations=[citation]))
        quoted = self._statuses(run)[0]["quoted"]

        self.assertNotIn("ghp_abcdefghijklmnopqrstuvwxyzABCDEF0123", quoted)
        self.assertIn("[REDACTED]", quoted)

    def test_the_emitted_citation_matches_the_published_schema(self):
        """Schema and document must not drift; nothing else exercises this one.

        The schema tests run the loop without an evidence base, so
        `citation_checks` is empty there and the nested citation object is
        never compared with what is published.
        """
        schema = json.loads(
            (Path(__file__).resolve().parents[1] / "schemas" / "atlas-evaluation.v1.json")
            .read_text(encoding="utf-8")
        )
        declared = schema["properties"]["citation_checks"]["items"]["properties"][
            "statuses"
        ]["items"]
        citation = self._statuses(self._run(self._passing_output()))[0]

        self.assertEqual(set(citation), set(declared["properties"]))
        self.assertEqual(set(declared["required"]) - set(citation), set())
