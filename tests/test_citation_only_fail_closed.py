"""A citation is not a check, and the run document must not say it was.

Post-merge review of #36. The exit criteria named what `repo_review` owes —
`claims_are_settled`, `citations_hold`, `findings_are_checkable` — and the
evaluator marked a criterion unmet only when some gap code said so. The older
citation-only path emits no gap when every finding merely *names* a source, so
all three were reported met on a run where nothing was checked at all.

The `passed` itself is older than #36 and was recorded as a known limitation
in `docs/api-contract.md`: on that path a factually wrong statement that
mentions `README.md` cleared the gate. What #36 added was a positive claim
about *why* it cleared it. Both are closed here by the same rule: without a
deterministic check, a cited finding does not settle anything.

The vacuous case is kept apart on purpose. A review that records its sources
and asserts no finding has nothing to settle, and nothing about it is untrue.
"""

from __future__ import annotations

import unittest
from typing import Any

from atlas_core import AtlasController
from atlas_core.adapters.model import ModelResult

REPO_TASK = "granska repo atlas-core"
README_OBS = "README.md:\n# Atlas Core\n\npip install atlas-core\n"

#: Demonstrably false about the source above, and it names that source.
FALSE_CLAIM = "README.md saknar helt installationsinstruktioner och nämner aldrig pip."

SECTIONS = "\n\n## Recommendation\nx\n\n## Next step\ny\n\n## Confidence\nLow.\n"


def _output(finding: str | None) -> str:
    body = "# Repo Review\n\n" + ("granskning " * 40) + "\n\n## Observed sources\n- README.md\n"
    if finding is not None:
        body += "\n## Findings\n- " + finding + "\n"
    return body + SECTIONS


class _Adapter:
    def __init__(self, output: str):
        self.output = output

    def execute(self, **kwargs: Any) -> ModelResult:
        return ModelResult(output=self.output, provider="test", model="fixture")


def _run(output: str, **kwargs: Any) -> dict[str, Any]:
    return AtlasController(max_iterations=1, model_adapter=_Adapter(output)).run(
        REPO_TASK, observations=[README_OBS], json_mode=True, **kwargs
    )


class TestACitedFindingIsNotASettledOne(unittest.TestCase):
    def test_a_false_finding_that_names_a_real_source_cannot_pass(self):
        """The regression this file exists for.

        Everything the older gate looked at is right here: sections present, a
        sources heading, and a finding naming a file that really was read. The
        claim is false, and nothing on this path ever compared it to anything.
        """
        run = _run(_output(FALSE_CLAIM))

        self.assertNotEqual(run["stop_reason"], "passed")
        self.assertFalse(run["evaluations"][-1]["passed"])

    def test_the_criteria_it_never_checked_are_reported_unmet(self):
        """#36's own contribution: claiming the criteria had been met."""
        evaluation = _run(_output(FALSE_CLAIM))["evaluations"][-1]

        self.assertIn("claims_are_settled", evaluation["unmet_criteria"])
        self.assertIn("citations_hold", evaluation["unmet_criteria"])
        self.assertIn("findings_are_checkable", evaluation["unmet_criteria"])

    def test_a_criterion_is_never_met_while_nothing_was_checked(self):
        """The invariant, not the instance.

        A met evidence criterion and an empty `citation_checks` cannot both be
        true: the first says a deterministic check decided something, and the
        second says none ran.
        """
        evaluation = _run(_output(FALSE_CLAIM))["evaluations"][-1]
        evidence_criteria = {
            "claims_are_settled",
            "citations_hold",
            "findings_are_checkable",
        }

        if not evaluation["citation_checks"]:
            self.assertEqual(
                evidence_criteria & set(evaluation["met_criteria"]),
                set(),
                "no evidence criterion may be met when nothing was checked",
            )

    def test_the_gap_says_a_check_never_ran(self):
        evaluation = _run(_output(FALSE_CLAIM))["evaluations"][-1]

        self.assertIn("claims_not_checked", evaluation["evidence_gaps"])
        self.assertIn(FALSE_CLAIM, evaluation["unverified_claims"])

    def test_the_fix_is_the_caller_s_and_the_action_says_so(self):
        """Re-wording cannot produce an evidence base. A producer cannot fix it."""
        evaluation = _run(_output(FALSE_CLAIM))["evaluations"][-1]
        action = evaluation["next_action"]

        self.assertEqual(action["kind"], "observe_again")
        self.assertEqual(action["actor"], "host")
        self.assertEqual(action["details"]["reason"], "no_evidence_base")

    def test_no_iteration_is_burned_trying_to_re_word_it(self):
        run = AtlasController(
            max_iterations=3, model_adapter=_Adapter(_output(FALSE_CLAIM))
        ).run(REPO_TASK, observations=[README_OBS], json_mode=True)

        self.assertEqual(run["iteration"], 1)
        self.assertEqual(run["stop_reason"], "insufficient_evidence")

    def test_a_true_finding_fares_exactly_the_same(self):
        """The rule is about what was established, not about what is true.

        A correct claim on this path is unchecked in precisely the way a false
        one is. Passing it would mean the gate had judged the claim, and it
        did not.
        """
        run = _run(_output('README.md innehåller raden "pip install atlas-core".'))

        self.assertFalse(run["evaluations"][-1]["passed"])
        self.assertIn("claims_not_checked", run["evaluations"][-1]["evidence_gaps"])


class TestTheVacuousCaseIsNotSweptUp(unittest.TestCase):
    """A review that asserts nothing has nothing to settle."""

    def test_a_review_with_no_findings_still_passes(self):
        run = _run(_output(None))

        self.assertEqual(run["stop_reason"], "passed")
        self.assertEqual(run["evaluations"][-1]["unmet_criteria"], [])
        self.assertIsNone(run["evaluations"][-1]["evidence_coverage"])

    def test_and_it_claims_nothing_in_the_ledger(self):
        run = _run(_output(None))

        self.assertEqual(run["evaluations"][-1]["unverified_claims"], [])
        self.assertEqual(run["evaluations"][-1]["citation_checks"], [])


class TestTheScoreSaysHowItWasComputed(unittest.TestCase):
    """The second contract change from the review: `quality_score` changed
    meaning under an unchanged field name."""

    def test_every_evaluation_names_its_scoring_method(self):
        evaluation = _run(_output(None))["evaluations"][-1]

        self.assertEqual(evaluation["score_method"], "criteria_met_share")

    def test_the_method_is_from_the_published_vocabulary(self):
        from atlas_core.state import SCORE_METHODS

        evaluation = _run(_output(None))["evaluations"][-1]

        self.assertIn(evaluation["score_method"], SCORE_METHODS)


if __name__ == "__main__":
    unittest.main()
