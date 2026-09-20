"""P0.2, box three: fact, hypothesis and recommendation kept apart.

ROADMAP.md P0.2. The run document already separated them — `citation_checks`
carries a verdict per finding and `unverified_claims` lists the rest — but the
text a human actually reads did not:

    - README.md lines 1-5 contain "pip install"
    - README.md är förmodligen svår att följa för nybörjare.
    ---
    Status: provisional
    Evidence gaps: uncheckable_findings

Two identical bullets under one heading, and a trailer naming a gap without
naming the claim. A reader could not tell which was settled against a source.
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any

from atlas_core import AtlasController, EvidenceBase, StubModelAdapter
from atlas_core.claim_check import ClaimKind, TypedClaim
from atlas_core.evaluator import ROUTE_EVALUATORS
from atlas_core.evidence import FINDINGS_FENCE
from atlas_core.finalizer import FACT, HYPOTHESIS, REFUTED, render_run_text
from atlas_core.snapshot import collect_observation, take_snapshot

README = "# Atlas Core\n\npip install atlas-core\n\nSlut.\n"

HYPOTHESIS_CLAIM = "README.md är förmodligen svår att följa för nybörjare."
RECOMMENDATION = "Skriv om README för nybörjare."


class _Run(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        (self.root / "README.md").write_text(README, encoding="utf-8")
        self.snapshot = take_snapshot(self.root)
        self.observation = collect_observation(self.snapshot, "README.md")
        self.base = EvidenceBase(snapshot=self.snapshot, observations=[self.observation])
        self.typed = TypedClaim(
            kind=ClaimKind.CONTAINS,
            source_id=self.observation.source_id,
            text="pip install",
        )
        self.fact = self.typed.render(
            self.observation.path,
            self.observation.line_start,
            self.observation.line_end,
        )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _output(self, *, bullets: list[str], typed: bool = True, kind: ClaimKind | None = None) -> str:
        findings: list[dict[str, Any]] = []
        if typed:
            chosen = kind or self.typed.kind
            findings = [
                {
                    "claim": TypedClaim(
                        kind=chosen,
                        source_id=self.observation.source_id,
                        text="pip install",
                    ).render(
                        self.observation.path,
                        self.observation.line_start,
                        self.observation.line_end,
                    ),
                    "scope": "README.md",
                    "severity": "P2",
                    "severity_rationale": "r",
                    "evidence": [
                        {
                            "source_id": self.observation.source_id,
                            "content_sha256": self.observation.content_sha256,
                            "line_start": self.observation.line_start,
                            "line_end": self.observation.line_end,
                            "quoted": self.observation.excerpt,
                        }
                    ],
                    "typed_claim": {
                        "kind": chosen.value,
                        "source_id": self.observation.source_id,
                        "text": "pip install",
                    },
                }
            ]
        body = "\n".join(f"- {bullet}" for bullet in bullets)
        text = f"""# Granskning

Genomgången nedan bygger på de källor som lästes denna körning och täcker
dokumentation och släppprocess i tillräcklig detalj för att motivera
slutsatserna. Texten är lång nog för att passera substanskravet i evalueringen.

## Observed sources
- `README.md`

## Findings
{body}

## Recommendation
{RECOMMENDATION}

## Next step
Börja med installationsavsnittet.

## Confidence
Medium.
"""
        if not findings:
            return text
        fence = "```" + FINDINGS_FENCE
        return text + "\n" + fence + "\n" + json.dumps(findings) + "\n```\n"

    def _text(self, output: str) -> str:
        controller = AtlasController(max_iterations=1, model_adapter=StubModelAdapter(output))
        return controller.run("granska repo", evidence=self.base)


class TestTheThreeKindsStaySeparate(_Run):
    """The box: fact, hypothesis and recommendation, through the whole run."""

    def test_a_fact_and_a_hypothesis_are_labelled_differently(self):
        text = self._text(self._output(bullets=[self.fact, HYPOTHESIS_CLAIM]))

        self.assertIn(f"{FACT}  {self.fact}", text)
        self.assertIn(f"{HYPOTHESIS}  {HYPOTHESIS_CLAIM}", text)

    def test_the_bullets_alone_still_look_identical(self):
        """What the ledger is for. The body is the producer's, unchanged."""
        text = self._text(self._output(bullets=[self.fact, HYPOTHESIS_CLAIM]))
        body = text.split("\n---\n")[0]

        self.assertIn(f"- {self.fact}", body)
        self.assertIn(f"- {HYPOTHESIS_CLAIM}", body)
        for label in (FACT, HYPOTHESIS, REFUTED):
            self.assertNotIn(label, body, "the ledger belongs in the trailer")

    def test_the_recommendation_is_not_listed_as_a_finding(self):
        text = self._text(self._output(bullets=[self.fact, HYPOTHESIS_CLAIM]))
        ledger = text.split("Claim ledger")[1]

        self.assertIn(RECOMMENDATION, text)
        self.assertNotIn(RECOMMENDATION, ledger)
        self.assertIn("Recommendations are advice, not findings", ledger)

    def test_a_refuted_claim_is_not_filed_as_a_hypothesis(self):
        """Three kinds, not two: the source actively saying otherwise differs."""
        text = self._text(
            self._output(
                bullets=[
                    TypedClaim(
                        kind=ClaimKind.LACKS,
                        source_id=self.observation.source_id,
                        text="pip install",
                    ).render("README.md", 1, 5)
                ],
                kind=ClaimKind.LACKS,
            )
        )

        self.assertIn(REFUTED, text)
        self.assertNotIn(FACT.strip() + "  ", text.split("Claim ledger")[1])

    def test_a_prose_finding_the_checker_never_saw_is_still_listed(self):
        """The claims most at risk of reading as established are the loose ones."""
        text = self._text(self._output(bullets=[HYPOTHESIS_CLAIM], typed=False))

        self.assertIn(f"{HYPOTHESIS}  {HYPOTHESIS_CLAIM}", text)

    def test_a_cited_but_unsettled_claim_is_a_hypothesis(self):
        """The case a negative control caught this suite missing.

        A finding with sound citations and no typed claim reaches
        `citation_checks` with `insufficient_evidence`. Labelling that branch
        FACT went undetected, because every other hypothesis in these tests
        arrives through `unverified_claims` instead.
        """
        finding = {
            "claim": HYPOTHESIS_CLAIM,
            "scope": "README.md",
            "severity": "P2",
            "severity_rationale": "r",
            "evidence": [
                {
                    "source_id": self.observation.source_id,
                    "content_sha256": self.observation.content_sha256,
                    "line_start": self.observation.line_start,
                    "line_end": self.observation.line_end,
                    "quoted": self.observation.excerpt,
                }
            ],
        }
        body = self._output(bullets=[HYPOTHESIS_CLAIM], typed=False)
        fence = "```" + FINDINGS_FENCE
        output = body + "\n" + fence + "\n" + json.dumps([finding]) + "\n```\n"

        run = AtlasController(
            max_iterations=1, model_adapter=StubModelAdapter(output)
        ).run("granska repo", evidence=self.base, json_mode=True)
        record = run["evaluations"][-1]["citation_checks"][0]
        text = render_run_text(run)

        self.assertTrue(record["citations_are_sound"])
        self.assertEqual(record["verdict"], "insufficient_evidence")
        self.assertIn(f"{HYPOTHESIS}  {HYPOTHESIS_CLAIM}", text)
        self.assertNotIn(f"{FACT}  {HYPOTHESIS_CLAIM}", text)

    def test_a_sound_citation_without_a_settled_claim_is_a_hypothesis(self):
        """Citation integrity is not establishment, and the label must agree."""
        run = AtlasController(
            max_iterations=1,
            model_adapter=StubModelAdapter(
                self._output(bullets=[self.fact, HYPOTHESIS_CLAIM])
            ),
        ).run("granska repo", evidence=self.base, json_mode=True)
        record = run["evaluations"][-1]["citation_checks"][0]

        self.assertTrue(record["citations_are_sound"])
        self.assertEqual(record["verdict"], "verified")
        self.assertIn(FACT, render_run_text(run))


class TestTheLedgerIsDerivedNotParsed(_Run):
    """From the run document, which is where the separation actually lives."""

    def test_the_ledger_ignores_what_the_body_claims(self):
        """A body that calls everything verified changes nothing."""
        output = self._output(bullets=[self.fact, HYPOTHESIS_CLAIM]).replace(
            "## Findings", "## Verified findings"
        )

        text = self._text(output)

        self.assertIn(f"{HYPOTHESIS}  {HYPOTHESIS_CLAIM}", text)

    def test_a_run_with_no_claims_gets_no_ledger(self):
        """A heading over nothing is noise, not honesty."""
        run = AtlasController(max_iterations=1).run("förklara loopen", json_mode=True)

        self.assertNotIn("Claim ledger", render_run_text(run))

    def test_a_long_claim_is_clipped_not_dropped(self):
        run = {
            "outputs": ["body"],
            "evaluations": [
                {
                    "quality_score": 0.5,
                    "passed": False,
                    "requires_user_approval": False,
                    "citation_checks": [
                        {"claim": "x" * 400, "verdict": "insufficient_evidence"}
                    ],
                    "unverified_claims": [],
                }
            ],
        }

        text = render_run_text(run)

        self.assertIn(HYPOTHESIS, text)
        self.assertIn("…", text)
        self.assertNotIn("x" * 200, text)

    def test_a_multiline_claim_does_not_break_the_column(self):
        run = {
            "outputs": ["body"],
            "evaluations": [
                {
                    "quality_score": 0.5,
                    "passed": False,
                    "requires_user_approval": False,
                    "citation_checks": [],
                    "unverified_claims": ["första raden\nandra raden"],
                }
            ],
        }

        ledger = render_run_text(run).split("Claim ledger")[1]
        # startswith, not `in`: the ledger's own footer names the labels when
        # it explains them, and counting those would measure nothing.
        rows = [line for line in ledger.splitlines() if line.startswith(f"  {HYPOTHESIS}  ")]

        self.assertEqual(len(rows), 1)
        self.assertIn("första raden andra raden", rows[0])


class TestTheHeadingDoesNotAssertVerification(unittest.TestCase):
    def test_a_plain_findings_heading_is_accepted(self):
        headings = ROUTE_EVALUATORS["repo_review"].finding_headings

        self.assertEqual(headings[0], "## Findings")

    def test_the_older_heading_still_works(self):
        """Existing producers must not break on a naming correction."""
        self.assertIn("## Verified findings", ROUTE_EVALUATORS["repo_review"].finding_headings)


if __name__ == "__main__":
    unittest.main()
