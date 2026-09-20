import unittest

from atlas_core.controller import AtlasController
from atlas_core.evaluator import evaluate
from atlas_core.executor import execute_plan
from atlas_core.planner import build_plan
from atlas_core.router import select_route
from atlas_core.state import AtlasEvaluation

ROUTE_TASKS = {
    "repo_review": "granska repo och hitta P0 P1 P2 förbättringar",
    "architecture_decision": "bygg målarkitektur för säker AI-assistent med Zero Trust",
    "root_cause": "hitta grundorsaken till varför releaseflödet fastnar",
    "decision_tradeoff": "jämför tre alternativ och rekommendera väg",
    "learning": "förklara hur det funkar som nybörjare",
    "prompt_improvement": "förbättra prompt för router",
    "general": "hej",
}


class TestLoop(unittest.TestCase):
    def test_loop_runs(self):
        c = AtlasController(max_iterations=2)
        result = c.run("jämför tre alternativ och rekommendera väg")
        self.assertTrue("Recommendation" in result or "recommendation" in result.lower())
        self.assertIn("Atlas route:", result)

    def test_write_requires_approval(self):
        c = AtlasController(max_iterations=2)
        result = c.run("skapa issue och pusha ändringen")
        self.assertIn("Write approval required", result)

    def test_every_route_stops_on_first_iteration(self):
        """README: the loop stops when the answer is good enough.

        Every shipped route must be able to satisfy the evaluator it is graded
        by, otherwise the loop burns its whole iteration budget on every run.

        repo_review is excluded deliberately. Since the P1 evidence evaluator it
        is graded on sources as well as shape, and a review of a repository
        nobody read cannot be "good enough" — it stops at one iteration, but as
        `no_actionable_retry` rather than `passed`. That case is covered by
        tests/test_evidence_evaluator.py.
        """
        for name, task in ROUTE_TASKS.items():
            if name == "repo_review":
                continue
            with self.subTest(route=name):
                state = AtlasController(max_iterations=2).run(task, json_mode=True)
                self.assertEqual(state["route"]["name"], name)
                evaluation = state["evaluations"][-1]
                self.assertTrue(
                    evaluation["passed"],
                    f"{name} scored {evaluation['quality_score']}, missing {evaluation['missing']}",
                )
                self.assertEqual(state["iteration"], 1)
                self.assertEqual(evaluation["missing_sections"], [])

    def test_repo_review_still_stops_on_the_first_pass_without_sources(self):
        """It must not burn the iteration budget either — just not by passing."""
        state = AtlasController(max_iterations=2).run(ROUTE_TASKS["repo_review"], json_mode=True)

        self.assertEqual(state["iteration"], 1)
        self.assertEqual(state["stop_reason"], "insufficient_evidence")
        self.assertFalse(state["evaluations"][-1]["passed"])

    def test_observations_reach_every_route(self):
        """README: run output embeds observed repo content."""
        state = AtlasController(max_iterations=2).run(
            "förbättra prompt för router",
            observations=["README.md:\n# Demo repo"],
            json_mode=True,
        )
        self.assertEqual(state["route"]["name"], "prompt_improvement")
        output = state["outputs"][-1]
        self.assertIn("## Sources inspected", output)
        self.assertIn("# Demo repo", output)

    def test_caller_observations_are_not_mutated(self):
        observations = ["README.md:\n# Demo repo"]
        AtlasController(max_iterations=2).run(
            "skapa issue och pusha ändringen", observations=observations
        )
        self.assertEqual(observations, ["README.md:\n# Demo repo"])


class TestRetry(unittest.TestCase):
    def _plan(self):
        return build_plan("granska repo", select_route(ROUTE_TASKS["repo_review"]))

    def test_retry_closes_the_gaps_evaluation_named(self):
        feedback = AtlasEvaluation(
            quality_score=0.7,
            passed=False,
            missing_sections=["recommendation", "next_step"],
        )
        output = execute_plan("granska repo", self._plan(), [], feedback=feedback)
        self.assertIn("## Loop improvement", output)
        self.assertIn("recommendation", output)
        self.assertIn("next_step", output)
        self.assertIn("Följ route 'repo_review' steg för steg", output)

    def test_no_improvement_claim_when_nothing_to_close(self):
        feedback = AtlasEvaluation(quality_score=0.7, passed=False, missing_sections=[])
        output = execute_plan("granska repo", self._plan(), [], feedback=feedback)
        self.assertNotIn("## Loop improvement", output)

    def test_retry_only_when_a_gap_is_actionable(self):
        complete_but_short = "## Recommendation\nx\n\n## Next step\ny\n\n## Confidence\nLow.\n"
        evaluation = evaluate("uppgift", complete_but_short, ["answers_task"], 1, 2)
        self.assertFalse(evaluation.passed)
        self.assertEqual(evaluation.missing_sections, [])
        self.assertFalse(evaluation.should_retry)

    def test_retry_when_a_section_is_missing(self):
        evaluation = evaluate("uppgift", "x" * 400, ["answers_task"], 1, 2)
        self.assertTrue(evaluation.should_retry)
        self.assertIn("recommendation", evaluation.missing_sections)


if __name__ == "__main__":
    unittest.main()
