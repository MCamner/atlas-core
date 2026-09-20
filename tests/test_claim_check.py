"""P0.2b: deciding whether the source supports the claim.

ROADMAP.md P0.2. The review that shaped this suite found that deciding a
*producer-chosen predicate* is not deciding the producer's *claim*, and that
the gap broke both strong verdicts:

    1. FALSKT pastaende, latt orelaterat villkor:   passed=True  verdict=verified
    2. SANT pastaende, orelaterat villkor refuterat: passed=False verdict=contradicted
    3. villkor uppfyllt av text BORTOM utdraget:     passed=True  verdict=verified

So the only route to `verified` or `contradicted` is a **typed claim**, where
the claim is the predicate and the human-readable sentence is derived from it.
Free text keeps `insufficient_evidence`, and a producer's own declared
condition settles that condition — which is why its results are named
`condition_supported` and `condition_refuted` and can never reach `PASS`.

Scope is the observed line range, not the file: `collect_observation` keeps a
bounded excerpt, and text nobody observed must not decide a verdict.
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any

from atlas_core import AtlasController, EvidenceBase, StubModelAdapter
from atlas_core.claim_check import (
    CLAIM_KINDS,
    SUPPORTED_KINDS,
    ClaimCondition,
    ClaimKind,
    ClaimResult,
    ConditionKind,
    TypedClaim,
    build_condition,
    build_typed_claim,
    check_typed_claim,
)
from atlas_core.evidence import FINDINGS_FENCE, structured_findings
from atlas_core.finding import EvidenceRef, Finding
from atlas_core.snapshot import collect_observation, take_snapshot

#: Five observed lines out of forty. The tail exists so a claim can be made
#: about text the run genuinely did not record.
README = (
    "# Atlas Core\n"
    "\n"
    "pip install atlas-core\n"
    "\n"
    "En avgränsad loop-motor.\n"
    + "".join(f"rad {index}\n" for index in range(6, 40))
    + "LICENS: MIT\n"
)

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

_DEFAULT: Any = object()


class _Loop(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        (self.root / "README.md").write_text(README, encoding="utf-8")
        self.snapshot = take_snapshot(self.root)
        self.observation = collect_observation(self.snapshot, "README.md", max_lines=5)
        self.base = EvidenceBase(snapshot=self.snapshot, observations=[self.observation])
        self.assertEqual(
            (self.observation.line_start, self.observation.line_end),
            (1, 5),
            "the fixture depends on observing a bounded excerpt",
        )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _render(self, kind: ClaimKind, text: str) -> str:
        """The sentence a typed claim derives, which the prose must equal."""
        return TypedClaim(
            kind=kind, source_id=self.observation.source_id, text=text
        ).render("README.md", 1, 5)

    def _typed(self, kind: ClaimKind, text: str) -> dict[str, Any]:
        return {
            "kind": kind.value,
            "source_id": self.observation.source_id,
            "text": text,
        }

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

    def _finding(self, claim: str, **extra: Any) -> dict[str, Any]:
        finding: dict[str, Any] = {
            "claim": claim,
            "scope": "README.md",
            "severity": "P1",
            "severity_rationale": "Blockerar en ny användare.",
            "evidence": [self._citation()],
        }
        finding.update(extra)
        return finding

    def _run(self, findings: list[dict[str, Any]], *, max_iterations: int = 1) -> Any:
        fence = "```" + FINDINGS_FENCE
        output = (
            PROSE.format(claim=findings[0]["claim"])
            + "\n" + fence + "\n" + json.dumps(findings) + "\n```\n"
        )
        controller = AtlasController(
            max_iterations=max_iterations, model_adapter=StubModelAdapter(output)
        )
        return controller.run("granska repo", evidence=self.base, json_mode=True)

    def _record(self, run: Any) -> dict[str, Any]:
        return run["evaluations"][-1]["citation_checks"][0]


class TestAFreeConditionCannotDecideAnything(_Loop):
    """The three cases the review reproduced, each asserted through `run()`."""

    def test_a_false_claim_with_an_easy_unrelated_condition_cannot_pass(self):
        """Review point 1. `# Atlas Core` is in the file; the claim is still false."""
        run = self._run(
            [
                self._finding(
                    "README.md saknar helt installationsinstruktioner och nämner aldrig pip.",
                    claim_check=self._typed(ClaimKind.CONTAINS, "# Atlas Core")
                    | {"kind": "present"},
                )
            ]
        )
        evaluation = run["evaluations"][-1]
        record = self._record(run)

        self.assertTrue(record["citations_are_sound"])
        self.assertEqual(record["claim_check"]["result"], "condition_supported")
        self.assertFalse(record["claim_check"]["is_decisive"])
        self.assertEqual(record["verdict"], "insufficient_evidence")
        self.assertFalse(evaluation["passed"])
        self.assertIn("unverified_findings", evaluation["evidence_gaps"])

    def test_a_true_claim_is_not_refuted_by_an_unrelated_condition(self):
        """Review point 2. The heading being present says nothing about pip."""
        run = self._run(
            [
                self._finding(
                    "README.md dokumenterar installation med pip.",
                    claim_check={
                        "kind": "absent",
                        "source_id": self.observation.source_id,
                        "text": "# Atlas Core",
                    },
                )
            ]
        )
        record = self._record(run)

        self.assertEqual(record["claim_check"]["result"], "condition_refuted")
        self.assertNotEqual(record["verdict"], "contradicted")
        self.assertEqual(record["verdict"], "insufficient_evidence")

    def test_a_refuted_condition_is_not_described_as_a_refuted_claim(self):
        """The wording has to carry the distinction, not only the enum value."""
        run = self._run(
            [
                self._finding(
                    "README.md dokumenterar installation med pip.",
                    claim_check={
                        "kind": "absent",
                        "source_id": self.observation.source_id,
                        "text": "# Atlas Core",
                    },
                )
            ]
        )
        reason = self._record(run)["claim_check"]["reason"]

        self.assertIn("settles the test and not the claim", reason)
        self.assertIn("producer's own test", reason)

    def test_a_condition_is_settled_only_over_the_observed_lines(self):
        """Review point 3. `LICENS: MIT` is at line 40; the run observed 1-5."""
        run = self._run(
            [
                self._finding(
                    "README.md anger sin licens.",
                    claim_check={
                        "kind": "present",
                        "source_id": self.observation.source_id,
                        "text": "LICENS: MIT",
                    },
                )
            ]
        )
        record = self._record(run)

        self.assertIn("LICENS: MIT", README)
        self.assertNotIn("LICENS: MIT", self.observation.excerpt)
        self.assertEqual(record["claim_check"]["result"], "condition_refuted")
        self.assertFalse(run["evaluations"][-1]["passed"])

    def test_free_text_alone_cannot_pass_either(self):
        run = self._run([self._finding("README.md saknar installationssteg.")])
        evaluation = run["evaluations"][-1]

        self.assertEqual(self._record(run)["claim_check"]["result"], "not_declared")
        self.assertFalse(evaluation["passed"])
        self.assertIn("unverified_findings", evaluation["evidence_gaps"])


class TestATypedClaimIsTheOnlyRouteToAStrongVerdict(_Loop):
    """The claim is the predicate, so relevance is structural, not asserted."""

    def test_a_true_typed_claim_is_verified_and_passes(self):
        claim = self._render(ClaimKind.CONTAINS, "pip install")

        run = self._run(
            [self._finding(claim, typed_claim=self._typed(ClaimKind.CONTAINS, "pip install"))]
        )
        record = self._record(run)

        self.assertEqual(claim, 'README.md lines 1-5 contain "pip install"')
        self.assertEqual(record["verdict"], "verified")
        self.assertEqual(record["verification_method"], "semantic")
        self.assertTrue(record["claim_check"]["is_decisive"])
        self.assertTrue(run["evaluations"][-1]["passed"])

    def test_a_false_typed_claim_is_contradicted_and_cannot_pass(self):
        claim = self._render(ClaimKind.LACKS, "pip install")

        run = self._run(
            [self._finding(claim, typed_claim=self._typed(ClaimKind.LACKS, "pip install"))]
        )
        evaluation = run["evaluations"][-1]

        self.assertEqual(self._record(run)["verdict"], "contradicted")
        self.assertFalse(evaluation["passed"])
        self.assertIn("contradicted_findings", evaluation["evidence_gaps"])

    def test_the_derived_sentence_names_the_range_it_was_settled_over(self):
        """A claim about five lines must not read as a claim about the file."""
        claim = self._render(ClaimKind.CONTAINS, "pip install")

        self.assertIn("lines 1-5", claim)

    def test_a_typed_claim_about_unobserved_text_is_contradicted_not_verified(self):
        """Review point 3 on the decisive path.

        `LICENS: MIT` is at line 40. The claim says lines 1-5 contain it, and
        they do not — so the refutation is correct, and the way to assert
        something about line 40 is to observe line 40.
        """
        claim = self._render(ClaimKind.CONTAINS, "LICENS: MIT")

        run = self._run(
            [self._finding(claim, typed_claim=self._typed(ClaimKind.CONTAINS, "LICENS: MIT"))]
        )
        record = self._record(run)

        self.assertIn("LICENS: MIT", README)
        self.assertEqual(record["verdict"], "contradicted")
        self.assertFalse(run["evaluations"][-1]["passed"])

    def test_prose_that_claims_more_than_the_typed_claim_is_refused(self):
        """The sentence a reader sees must be the sentence that was settled."""
        run = self._run(
            [
                self._finding(
                    "README.md saknar all dokumentation.",
                    typed_claim=self._typed(ClaimKind.CONTAINS, "pip install"),
                )
            ]
        )
        evaluation = run["evaluations"][-1]
        record = self._record(run)

        self.assertEqual(record["claim_check"]["result"], "claim_text_mismatch")
        self.assertFalse(record["claim_check"]["is_decisive"])
        self.assertEqual(record["verdict"], "insufficient_evidence")
        self.assertFalse(evaluation["passed"])
        self.assertIn("claim_text_mismatch", evaluation["evidence_gaps"])

    def test_the_expected_sentence_is_handed_back_verbatim(self):
        """Derived text is unguessable, so the repair has to be stated."""
        run = self._run(
            [
                self._finding(
                    "README.md saknar all dokumentation.",
                    typed_claim=self._typed(ClaimKind.CONTAINS, "pip install"),
                )
            ],
            max_iterations=2,
        )
        adjustment = run["evaluations"][0]["suggested_adjustment"] or ""

        self.assertIn('README.md lines 1-5 contain "pip install"', adjustment)

    def test_a_typed_claim_and_a_condition_together_are_refused(self):
        """Two tests of one claim could only disagree."""
        parsed = structured_findings(
            "```" + FINDINGS_FENCE + "\n"
            + json.dumps(
                [
                    self._finding(
                        "x",
                        typed_claim=self._typed(ClaimKind.CONTAINS, "pip"),
                        claim_check={
                            "kind": "present",
                            "source_id": self.observation.source_id,
                            "text": "pip",
                        },
                    )
                ]
            )
            + "\n```"
        )

        self.assertIn("not both", parsed.malformed or "")


class TestTheModelIsNotItsOwnJudge(_Loop):
    """ROADMAP P0.2: "modellens eget självomdöme får inte ensamt ge PASS"."""

    def test_a_producer_cannot_declare_its_own_verdict(self):
        block = json.loads(
            (Path(__file__).parents[1] / "schemas" / "atlas-findings-block.v1.json")
            .read_text(encoding="utf-8")
        )
        properties = block["items"]["properties"]

        for assigned in ("verdict", "verification_method", "finding_id"):
            self.assertNotIn(assigned, properties)

    def test_a_smuggled_verdict_is_refused_not_honoured(self):
        finding = self._finding("x")
        finding["verdict"] = "verified"

        parsed = structured_findings(
            "```" + FINDINGS_FENCE + "\n" + json.dumps([finding]) + "\n```"
        )

        self.assertIsNotNone(parsed.malformed)

    def test_only_the_semantic_module_constructs_the_two_strong_verdicts(self):
        """`finding.py`'s structural guarantee must still hold."""
        import re

        source = (
            Path(__file__).parents[1] / "atlas_core" / "finding.py"
        ).read_text(encoding="utf-8")
        constructions = [
            line.strip()
            for line in source.splitlines()
            if re.search(
                r'(verdict\s*=\s*"(verified|contradicted)"|return\s+"(verified|contradicted)")',
                line,
            )
        ]

        self.assertEqual(constructions, [])


class TestUnsoundCitationsNeverReachTheClaimCheck(_Loop):
    """A refutation resting on the wrong file would be an accusation."""

    def test_a_miscited_finding_is_not_refuted(self):
        claim = self._render(ClaimKind.LACKS, "pip install")
        finding = self._finding(claim, typed_claim=self._typed(ClaimKind.LACKS, "pip install"))
        finding["evidence"] = [self._citation(quoted="FEL")]

        record = self._record(self._run([finding]))

        self.assertFalse(record["citations_are_sound"])
        self.assertIsNone(record["claim_check"])
        self.assertNotEqual(record["verdict"], "contradicted")

    def test_a_claim_about_an_uncited_source_settles_nothing(self):
        claim = self._render(ClaimKind.CONTAINS, "pip install")
        run = self._run(
            [
                self._finding(
                    claim,
                    typed_claim={
                        "kind": "source_contains_literal",
                        "source_id": "0" * 16,
                        "text": "pip install",
                    },
                )
            ]
        )
        record = self._record(run)

        self.assertEqual(record["claim_check"]["result"], "source_not_cited")
        self.assertEqual(record["verdict"], "insufficient_evidence")


class TestAStaleSourceSettlesNothing(_Loop):
    """In either direction. Refuting with unobserved content is as wrong."""

    def _finding_object(self) -> Finding:
        return Finding.create(
            claim=self._render(ClaimKind.LACKS, "pip install"),
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

    def _claim(self) -> TypedClaim:
        return TypedClaim(
            kind=ClaimKind.LACKS,
            source_id=self.observation.source_id,
            text="pip install",
        )

    def test_a_changed_file_is_unavailable_not_refuting(self):
        (self.root / "README.md").write_text("helt annat\n", encoding="utf-8")

        verdict = check_typed_claim(
            self._finding_object(), self._claim(), [self.observation], self.root
        )

        self.assertEqual(verdict.result, ClaimResult.SOURCE_UNAVAILABLE)
        self.assertFalse(verdict.is_decisive())

    def test_a_deleted_file_is_unavailable(self):
        (self.root / "README.md").unlink()

        verdict = check_typed_claim(
            self._finding_object(), self._claim(), [self.observation], self.root
        )

        self.assertEqual(verdict.result, ClaimResult.SOURCE_UNAVAILABLE)

    def test_an_intact_file_still_settles_the_claim(self):
        """Negative control for the two above."""
        verdict = check_typed_claim(
            self._finding_object(), self._claim(), [self.observation], self.root
        )

        self.assertEqual(verdict.result, ClaimResult.CONTRADICTED)
        self.assertTrue(verdict.is_decisive())


class TestTheDeclaredForms(unittest.TestCase):
    def test_an_absent_declaration_is_not_an_error(self):
        self.assertIsNone(build_typed_claim(None))
        self.assertIsNone(build_condition(None))

    def test_only_two_claim_kinds_exist(self):
        self.assertEqual(
            CLAIM_KINDS, frozenset({"source_contains_literal", "source_lacks_literal"})
        )

    def test_regular_expressions_are_not_accepted(self):
        """A producer-supplied pattern is untrusted input that can hang a checker."""
        self.assertEqual(SUPPORTED_KINDS, frozenset({"absent", "present"}))

        with self.assertRaises(ValueError):
            build_typed_claim({"kind": "regex", "source_id": "a", "text": "x"})

    def test_a_pattern_is_matched_literally_not_as_a_regex(self):
        claim = TypedClaim(kind=ClaimKind.CONTAINS, source_id="a", text="a.*b")

        self.assertTrue(claim.holds_for("x a.*b y"))
        self.assertFalse(claim.holds_for("aXXXb"))

    def test_empty_text_is_refused_in_both_forms(self):
        for build in (
            lambda: TypedClaim(kind=ClaimKind.CONTAINS, source_id="a", text=""),
            lambda: ClaimCondition(kind=ConditionKind.ABSENT, source_id="a", text=""),
        ):
            with self.assertRaises(ValueError) as raised:
                build()
            self.assertIn("settle nothing", str(raised.exception))

    def test_a_malformed_declaration_is_not_treated_as_none(self):
        """Trying and failing is a producer bug; saying nothing may be honest."""
        parsed = structured_findings(
            "```" + FINDINGS_FENCE + "\n"
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
                        "typed_claim": {"kind": "source_contains_literal"},
                    }
                ]
            )
            + "\n```"
        )

        self.assertIsNotNone(parsed.malformed)


class TestRetryIsOfferedForRepairableFindings(_Loop):
    def test_a_contradicted_finding_is_worth_another_pass(self):
        """The producer can drop or correct what the source refutes."""
        claim = self._render(ClaimKind.LACKS, "pip install")
        run = self._run(
            [self._finding(claim, typed_claim=self._typed(ClaimKind.LACKS, "pip install"))],
            max_iterations=2,
        )
        evaluation = run["evaluations"][0]

        self.assertTrue(evaluation["should_retry"])
        self.assertIn("refutes", evaluation["suggested_adjustment"] or "")

    def test_a_free_text_finding_is_told_to_state_a_typed_claim(self):
        run = self._run([self._finding("README.md saknar steg.")], max_iterations=2)
        adjustment = run["evaluations"][0]["suggested_adjustment"] or ""

        self.assertTrue(run["evaluations"][0]["should_retry"])
        self.assertIn("source_contains_literal", adjustment)


if __name__ == "__main__":
    unittest.main()
