"""P0.2b: whether the source supports the claim.

ROADMAP.md P0.2. Citation integrity established that a pointer holds and said
nothing about the claim. The gap was demonstrable through the whole loop: a
README containing `pip install atlas-core` backed a finding asserting it
"saknar helt installationsinstruktioner och nämner aldrig pip", with a sound
citation and `passed: True`.

The design this suite pins: the producer declares **what would make its claim
false**, and a deterministic checker settles it. The model is not its own
judge, and the two outcomes are not treated as equals — `test_a_condition_that
_holds_does_not_establish_the_claim` states the residual instead of glossing it.
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any

from atlas_core import AtlasController, EvidenceBase, StubModelAdapter
from atlas_core.claim_check import (
    ClaimCondition,
    ClaimKind,
    ClaimResult,
    build_condition,
    check_claim,
)
from atlas_core.evidence import FINDINGS_FENCE, structured_findings
from atlas_core.finding import EvidenceRef, Finding, check_finding
from atlas_core.snapshot import collect_observation, take_snapshot

README = "# Atlas Core\n\npip install atlas-core\n\nEn avgränsad loop-motor.\n"

PROSE = """# Repogranskning

Genomgången nedan bygger på de källor som lästes denna körning och täcker
dokumentation, testupplägg och släppprocess i tillräcklig detalj för att
motivera slutsatserna. Texten är lång nog för att passera substanskravet,
eftersom poängen är vad som händer när formen är korrekt men sakinnehållet
inte stämmer med källan.

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

#: The claim the roadmap names. The README says the opposite, in so many words.
FALSE_CLAIM = "README.md nämner aldrig pip och saknar installationsinstruktioner."
TRUE_CLAIM = "README.md dokumenterar installation med pip."

#: Distinguishes "caller said nothing" from "caller said no condition".
_DEFAULT: Any = object()


class _Loop(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        (self.root / "README.md").write_text(README, encoding="utf-8")
        self.snapshot = take_snapshot(self.root)
        self.observation = collect_observation(self.snapshot, "README.md")
        self.base = EvidenceBase(snapshot=self.snapshot, observations=[self.observation])

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _citation(self, **overrides: Any) -> dict[str, Any]:
        fields: dict[str, Any] = {
            "source_id": self.observation.source_id,
            "content_sha256": self.observation.content_sha256,
            "line_start": 1,
            "line_end": 1,
            "quoted": "# Atlas Core",
        }
        fields.update(overrides)
        return fields

    def _finding(
        self,
        claim: str = FALSE_CLAIM,
        claim_check: dict[str, Any] | None | Any = _DEFAULT,
    ) -> dict[str, Any]:
        finding: dict[str, Any] = {
            "claim": claim,
            "scope": "README.md",
            "severity": "P1",
            "severity_rationale": "Blockerar en ny användare.",
            "evidence": [self._citation()],
        }
        if claim_check is _DEFAULT:
            # The condition the false claim implies: if the README never
            # mentions pip, `pip install` is absent from it.
            claim_check = {
                "kind": "absent",
                "source_id": self.observation.source_id,
                "text": "pip install",
            }
        if claim_check is not None:
            finding["claim_check"] = claim_check
        return finding

    def _run(self, findings: list[dict[str, Any]], *, max_iterations: int = 1) -> Any:
        fence = "```" + FINDINGS_FENCE
        output = (
            PROSE.format(claim=findings[0]["claim"])
            + "\n"
            + fence
            + "\n"
            + json.dumps(findings)
            + "\n```\n"
        )
        controller = AtlasController(
            max_iterations=max_iterations, model_adapter=StubModelAdapter(output)
        )
        return controller.run("granska repo", evidence=self.base, json_mode=True)


class TestTheRoadmapCase(_Loop):
    """The exact behaviour P0.2b was defined by, through the whole run."""

    def test_a_false_claim_with_a_sound_citation_is_contradicted(self):
        """Not merely blocked — refuted, by the finding's own test for being wrong."""
        run = self._run([self._finding()])
        evaluation = run["evaluations"][-1]
        record = evaluation["citation_checks"][0]

        self.assertIn("pip install", README)
        self.assertTrue(record["citations_are_sound"])
        self.assertEqual(record["verdict"], "contradicted")
        self.assertEqual(record["claim_check"]["result"], "refuted")
        self.assertFalse(evaluation["passed"])
        self.assertIn("contradicted_findings", evaluation["evidence_gaps"])

    def test_a_false_claim_that_declares_nothing_is_insufficient_not_passed(self):
        """The other acceptable outcome: unchecked, and therefore not a pass."""
        run = self._run([self._finding(claim_check=None)])
        evaluation = run["evaluations"][-1]
        record = evaluation["citation_checks"][0]

        self.assertTrue(record["citations_are_sound"])
        self.assertEqual(record["verdict"], "insufficient_evidence")
        self.assertFalse(evaluation["passed"])
        self.assertIn("unverified_findings", evaluation["evidence_gaps"])

    def test_the_same_answer_passed_before_the_claim_check(self):
        """What P0.2b is worth, kept visible instead of deleted.

        With the route's claim requirement off, the false finding is graded on
        citation integrity alone — which it satisfies.
        """
        from atlas_core.evaluator import ROUTE_EVALUATORS
        from dataclasses import replace as _replace
        from atlas_core.evaluator import evaluate

        contract = _replace(ROUTE_EVALUATORS["repo_review"], requires_claim_check=False)
        fence = "```" + FINDINGS_FENCE
        output = (
            PROSE.format(claim=FALSE_CLAIM)
            + "\n" + fence + "\n" + json.dumps([self._finding()]) + "\n```\n"
        )
        ROUTE_EVALUATORS["repo_review"] = contract
        try:
            evaluation = evaluate(
                "granska repo", output, [], 1, 1,
                route_name="repo_review", evidence_base=self.base,
            )
        finally:
            ROUTE_EVALUATORS["repo_review"] = _replace(contract, requires_claim_check=True)

        self.assertTrue(evaluation.passed)
        self.assertEqual(evaluation.evidence_gaps, [])


class TestATrueClaimSurvives(_Loop):
    """Negative control: the gate must not refuse everything."""

    def test_a_declared_condition_that_holds_passes(self):
        run = self._run(
            [
                self._finding(
                    claim=TRUE_CLAIM,
                    claim_check={
                        "kind": "present",
                        "source_id": self.observation.source_id,
                        "text": "pip install",
                    },
                )
            ]
        )
        evaluation = run["evaluations"][-1]
        record = evaluation["citation_checks"][0]

        self.assertTrue(evaluation["passed"])
        self.assertEqual(record["verdict"], "verified")
        self.assertEqual(record["verification_method"], "semantic")
        self.assertEqual(record["claim_check"]["result"], "supported")

    def test_a_condition_that_holds_does_not_establish_the_claim(self):
        """The residual, stated in the run rather than left for a reader to find.

        Nothing checks that the declared condition is a fair test of the claim.
        A producer that declares an easy condition gets an easy `verified`, and
        the reasons must not read as though the claim were confirmed.
        """
        run = self._run(
            [
                self._finding(
                    claim="README.md är ett mästerverk.",
                    claim_check={
                        "kind": "present",
                        "source_id": self.observation.source_id,
                        "text": "#",
                    },
                )
            ]
        )
        reasons = " ".join(run["evaluations"][-1]["reasons"])

        self.assertTrue(run["evaluations"][-1]["passed"])
        self.assertIn("not that the condition captures the claim", reasons)


class TestTheModelIsNotItsOwnJudge(_Loop):
    """ROADMAP P0.2: "modellens eget självomdöme får inte ensamt ge PASS"."""

    def test_a_producer_cannot_declare_its_own_verdict(self):
        """`verdict` is not in the producer's input schema at all."""
        block = json.loads(
            (Path(__file__).parents[1] / "schemas" / "atlas-findings-block.v1.json")
            .read_text(encoding="utf-8")
        )
        properties = block["items"]["properties"]

        for assigned in ("verdict", "verification_method", "finding_id"):
            self.assertNotIn(assigned, properties)

    def test_a_smuggled_verdict_is_refused_not_honoured(self):
        finding = self._finding()
        finding["verdict"] = "verified"

        parsed = structured_findings(
            "```" + FINDINGS_FENCE + "\n" + json.dumps([finding]) + "\n```"
        )

        self.assertIsNotNone(parsed.malformed)

    def test_only_the_semantic_module_constructs_the_two_strong_verdicts(self):
        """`finding.py`'s structural guarantee must still hold after P0.2b.

        Reaching `verified` or `contradicted` requires a declared condition and
        a source that settled it, so the words stay out of the citation layer.
        """
        import re

        source = (
            Path(__file__).parents[1] / "atlas_core" / "finding.py"
        ).read_text(encoding="utf-8")
        constructions = [
            line.strip()
            for line in source.splitlines()
            if re.search(r'(verdict\s*=\s*"(verified|contradicted)"|return\s+"(verified|contradicted)")', line)
        ]

        self.assertEqual(constructions, [])


class TestUnsoundCitationsNeverReachTheClaimCheck(_Loop):
    """A refutation resting on the wrong file would be an accusation, not a check."""

    def test_a_miscited_finding_is_not_refuted(self):
        run = self._run([{**self._finding(), "evidence": [self._citation(quoted="FEL")]}])
        record = run["evaluations"][-1]["citation_checks"][0]

        self.assertFalse(record["citations_are_sound"])
        self.assertIsNone(record["claim_check"])
        self.assertNotEqual(record["verdict"], "contradicted")

    def test_a_condition_about_an_uncited_source_settles_nothing(self):
        other = collect_observation(self.snapshot, "README.md")
        run = self._run(
            [self._finding(claim_check={"kind": "absent", "source_id": "0" * 16, "text": "x"})]
        )
        record = run["evaluations"][-1]["citation_checks"][0]

        self.assertEqual(record["claim_check"]["result"], "source_not_cited")
        self.assertEqual(record["verdict"], "insufficient_evidence")
        self.assertEqual(other.source_id, self.observation.source_id)


class TestAStaleSourceSettlesNothing(_Loop):
    """In either direction. Refuting with content never observed is as wrong."""

    def _condition(self, **overrides: Any) -> ClaimCondition:
        fields: dict[str, Any] = {
            "kind": ClaimKind.ABSENT,
            "source_id": self.observation.source_id,
            "text": "pip install",
        }
        fields.update(overrides)
        return ClaimCondition(**fields)

    def _finding_object(self):
        return Finding.create(
            claim=FALSE_CLAIM,
            scope="README.md",
            severity="P1",
            severity_rationale="r",
            evidence=[
                EvidenceRef(
                    source_id=self.observation.source_id,
                    content_sha256=self.observation.content_sha256,
                    line_start=1,
                    line_end=1,
                    quoted="# Atlas Core",
                )
            ],
        )

    def test_a_changed_file_is_unavailable_not_refuting(self):
        (self.root / "README.md").write_text("helt annat\n", encoding="utf-8")

        verdict = check_claim(
            self._finding_object(), self._condition(), [self.observation], self.root
        )

        self.assertEqual(verdict.result, ClaimResult.SOURCE_UNAVAILABLE)
        self.assertFalse(verdict.refutes())
        self.assertFalse(verdict.supports())

    def test_a_deleted_file_is_unavailable(self):
        (self.root / "README.md").unlink()

        verdict = check_claim(
            self._finding_object(), self._condition(), [self.observation], self.root
        )

        self.assertEqual(verdict.result, ClaimResult.SOURCE_UNAVAILABLE)

    def test_an_intact_file_still_refutes(self):
        """Negative control for the two above."""
        verdict = check_claim(
            self._finding_object(), self._condition(), [self.observation], self.root
        )

        self.assertEqual(verdict.result, ClaimResult.REFUTED)


class TestTheConditionForm(unittest.TestCase):
    def test_an_absent_declaration_is_not_an_error(self):
        self.assertIsNone(build_condition(None))

    def test_an_unknown_kind_is_refused(self):
        with self.assertRaises(ValueError) as raised:
            build_condition({"kind": "regex", "source_id": "a", "text": "x"})

        self.assertIn("absent", str(raised.exception))

    def test_regular_expressions_are_not_accepted(self):
        """A producer-supplied pattern is untrusted input that can hang a checker."""
        from atlas_core.claim_check import SUPPORTED_KINDS

        self.assertEqual(SUPPORTED_KINDS, frozenset({"absent", "present"}))

    def test_a_pattern_is_matched_literally_not_as_a_regex(self):
        condition = ClaimCondition(
            kind=ClaimKind.PRESENT, source_id="a", text="a.*b"
        )

        self.assertTrue(condition.holds_for("x a.*b y"))
        self.assertFalse(condition.holds_for("aXXXb"))

    def test_empty_text_is_refused(self):
        with self.assertRaises(ValueError) as raised:
            ClaimCondition(kind=ClaimKind.ABSENT, source_id="a", text="")

        self.assertIn("settle nothing", str(raised.exception))

    def test_a_malformed_declaration_is_not_treated_as_none(self):
        """Trying and failing is a producer bug; saying nothing may be honest."""
        parsed = structured_findings(
            "```"
            + FINDINGS_FENCE
            + "\n"
            + json.dumps(
                [
                    {
                        "claim": "x",
                        "scope": "y",
                        "severity_rationale": "r",
                        "evidence": [
                            {
                                "source_id": "a",
                                "content_sha256": "a" * 64,
                                "line_start": 1,
                                "line_end": 1,
                                "quoted": "q",
                            }
                        ],
                        "claim_check": {"kind": "absent"},
                    }
                ]
            )
            + "\n```"
        )

        self.assertIsNotNone(parsed.malformed)


class TestRetryIsOfferedForRepairableClaims(_Loop):
    def test_a_refuted_finding_is_worth_another_pass(self):
        """The producer can drop or correct what the source refutes."""
        run = self._run([self._finding()], max_iterations=2)
        evaluation = run["evaluations"][0]

        self.assertTrue(evaluation["should_retry"])
        self.assertIn("refutes", evaluation["suggested_adjustment"] or "")

    def test_an_undeclared_finding_is_told_what_to_declare(self):
        run = self._run([self._finding(claim_check=None)], max_iterations=2)
        adjustment = run["evaluations"][0]["suggested_adjustment"] or ""

        self.assertTrue(run["evaluations"][0]["should_retry"])
        self.assertIn("claim_check", adjustment)
        self.assertIn("absent", adjustment)


if __name__ == "__main__":
    unittest.main()
