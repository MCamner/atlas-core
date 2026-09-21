"""P1.1 box three: what it takes to be done, named per route.

Two requirements, and they are separate things.

**Exit criteria instead of a score.** A run used to pass by collecting enough
weight: 0.45 to begin with, 0.15 for being longer than three hundred
characters, a little more per heading present, multiplied by an evidence
factor, compared against 0.78. Nothing in that arithmetic said what the route
owed, and an answer could clear the bar with a required section missing — a
run that met its gate while a declared requirement went unmet. Each route now
names its criteria, every one of them has to be met, and `quality_score`
reports the share met rather than deciding anything.

**No verified severity without coverage.** A producer declares `P1` before
anything is checked. When the check does not establish the claim, that number
must not travel on as though it had been assessed.
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
from atlas_core.claim_check import ClaimKind, TypedClaim
from atlas_core.evaluator import EXIT_CRITERIA, criteria_for
from atlas_core.evidence import FINDINGS_FENCE
from atlas_core.evidence_base import EvidenceBase
from atlas_core.observation import Observation
from atlas_core.snapshot import collect_observation, take_snapshot

README = "# Atlas Core\n\npip install atlas-core\n\nEn avgränsad loop-motor.\n"
REPO_TASK = "granska repo atlas-core"

BODY = """# Repogranskning

Granskningen nedan bygger på de källor som lästes denna körning och går igenom
repots dokumentation och släppprocess i tillräcklig detalj för att motivera de
slutsatser som dras.

## Observed sources
- `README.md`

## Findings
- {claim}
"""

SECTIONS = """
## Recommendation
Behåll installationsraden.

## Next step
Kör om mot en färsk snapshot.

## Confidence
Hög.
"""


class _Adapter:
    def __init__(self, output: str):
        self.output = output
        self.calls = 0

    def execute(self, **kwargs: Any) -> ModelResult:
        self.calls += 1
        return ModelResult(output=self.output, provider="test", model="fixture")


class _Repo(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (self.root / "README.md").write_text(README, encoding="utf-8")
        self.snapshot = take_snapshot(self.root)
        self.observation = collect_observation(self.snapshot, "README.md")
        self.base = EvidenceBase(
            snapshot=self.snapshot, observations=[self.observation]
        )

    def _settled(self, observation: Observation | None = None) -> dict[str, Any]:
        """A finding that is actually established against observed lines."""
        observation = observation or self.observation
        typed = TypedClaim(
            kind=ClaimKind.CONTAINS,
            source_id=observation.source_id,
            text="pip install",
        )
        claim = typed.render(
            observation.path, observation.line_start, observation.line_end
        )
        line = next(
            index + 1
            for index, content in enumerate(observation.excerpt.splitlines())
            if "pip install" in content
        )
        return {
            "claim": claim,
            "scope": observation.path,
            "severity": "P1",
            "severity_rationale": "Första steget en ny användare tar.",
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

    def _unsettled(self) -> dict[str, Any]:
        """Same shape, stated as free text, so nothing settles it."""
        finding = self._settled()
        finding.pop("typed_claim")
        finding["claim"] = "README.md är förmodligen svår att följa för nybörjare."
        return finding

    def _output(self, finding: dict[str, Any], *, sections: bool = True) -> str:
        text = BODY.format(claim=finding["claim"]) + (SECTIONS if sections else "")
        return text + "\n```" + FINDINGS_FENCE + "\n" + json.dumps([finding]) + "\n```\n"

    def _run(self, output: str) -> dict[str, Any]:
        return AtlasController(max_iterations=1, model_adapter=_Adapter(output)).run(
            REPO_TASK, evidence=self.base, json_mode=True
        )


class TestCriteriaAreNamedAndAllRequired(_Repo):
    def test_a_met_run_lists_every_criterion_as_met(self):
        run = self._run(self._output(self._settled()))
        evaluation = run["evaluations"][-1]

        self.assertEqual(run["stop_reason"], "passed")
        self.assertEqual(evaluation["unmet_criteria"], [])
        self.assertEqual(
            sorted(evaluation["met_criteria"]),
            sorted(code for code, _ in criteria_for("repo_review")),
        )

    def test_a_missing_section_is_now_enough_to_fail(self):
        """The behaviour this box exists to change.

        Under the weighted score an answer could clear 0.78 with a declared
        section missing, so a run reported that it had met its gate while a
        requirement its own route had named went unmet.
        """
        run = self._run(self._output(self._settled(), sections=False))
        evaluation = run["evaluations"][-1]

        self.assertNotEqual(run["stop_reason"], "passed")
        self.assertFalse(evaluation["passed"])
        self.assertEqual(
            sorted(evaluation["unmet_criteria"]),
            ["confidence", "next_step", "recommendation"],
        )

    def test_an_evidence_gap_names_the_criterion_it_fails(self):
        run = self._run(self._output(self._unsettled()))

        self.assertIn("claims_are_settled", run["evaluations"][-1]["unmet_criteria"])

    def test_the_score_reports_and_does_not_decide(self):
        """`quality_score` is the share met. Nothing branches on it."""
        run = self._run(self._output(self._settled(), sections=False))
        evaluation = run["evaluations"][-1]

        total = len(criteria_for("repo_review"))
        met = len(evaluation["met_criteria"])
        self.assertEqual(evaluation["quality_score"], round(met / total, 2))
        self.assertFalse(evaluation["passed"])

    def test_length_is_no_longer_a_criterion_for_a_route_that_checks_evidence(self):
        """A short review whose claims hold is done. Words are not the gate."""
        finding = self._settled()
        short = (
            "# Granskning\n\n## Observed sources\n- `README.md`\n\n## Findings\n- "
            + finding["claim"]
            + SECTIONS
            + "\n```"
            + FINDINGS_FENCE
            + "\n"
            + json.dumps([finding])
            + "\n```\n"
        )

        run = self._run(short)

        self.assertLess(len(short), 900)
        self.assertEqual(run["stop_reason"], "passed")

    def test_a_route_with_no_evidence_contract_declares_its_own_criteria(self):
        """Named rather than folded into a weighted sum. The proxy stays visible."""
        self.assertIn("substance", dict(criteria_for("general")))
        self.assertNotIn("substance", dict(criteria_for("repo_review")))
        self.assertNotIn("citations_hold", dict(criteria_for("general")))

    def test_every_criterion_states_what_it_requires(self):
        """A code with no sentence behind it is a gate nobody can read."""
        for route, criteria in EXIT_CRITERIA.items():
            for code, requirement in criteria:
                with self.subTest(route=route, code=code):
                    self.assertTrue(requirement.strip())
                    self.assertTrue(code.strip())


class TestSeverityNeedsCoverage(_Repo):
    def test_an_unsettled_finding_loses_its_declared_severity(self):
        run = self._run(self._output(self._unsettled()))
        record = run["evaluations"][-1]["citation_checks"][0]

        self.assertNotEqual(record["verdict"], "verified")
        self.assertEqual(record["severity"], "unknown")
        self.assertEqual(record["declared_severity"], "P1")

    def test_a_verified_finding_keeps_the_severity_it_declared(self):
        run = self._run(self._output(self._settled()))
        record = run["evaluations"][-1]["citation_checks"][0]

        self.assertEqual(record["verdict"], "verified")
        self.assertEqual(record["severity"], "P1")
        self.assertEqual(record["declared_severity"], "P1")

    def test_a_refuted_finding_does_not_keep_a_severity_either(self):
        """Refuted is decisive and still not coverage for the severity.

        The source says the claim is false. Whatever the producer thought the
        impact was, it was assessing something that is not the case.
        """
        typed = TypedClaim(
            kind=ClaimKind.LACKS,
            source_id=self.observation.source_id,
            text="pip install",
        )
        finding = self._settled()
        finding["claim"] = typed.render(
            self.observation.path,
            self.observation.line_start,
            self.observation.line_end,
        )
        finding["typed_claim"] = {
            "kind": typed.kind.value,
            "source_id": typed.source_id,
            "text": typed.text,
        }

        run = self._run(self._output(finding))
        record = run["evaluations"][-1]["citation_checks"][0]

        self.assertEqual(record["verdict"], "contradicted")
        self.assertEqual(record["severity"], "unknown")
        self.assertEqual(record["declared_severity"], "P1")

    def test_the_producer_still_states_a_severity_and_a_reason(self):
        """Dropping the field would lose the producer's own assessment.

        What the producer thought is worth keeping; presenting it as
        established is what must not happen.
        """
        run = self._run(self._output(self._unsettled()))
        record = run["evaluations"][-1]["citation_checks"][0]

        self.assertEqual(record["declared_severity"], "P1")
        self.assertIn("severity_rationale", record)


if __name__ == "__main__":
    unittest.main()
