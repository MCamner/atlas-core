"""P1: the evaluator grades whether findings are supported, not how they look.

Roadmap docs/ROADMAP-LOOP.md phase P1, Definition of Done:

- A well-formatted but incorrect response cannot receive PASS.
- A claim without evidence is marked as unverified.
- The evaluator can explain exactly why another iteration is needed.

The formatting checks that used to be the whole evaluation stay, but as a
separate secondary signal — `missing_sections` — so a route can still be told
it forgot a heading without that being confused for evidence.
"""

import json
import unittest
from pathlib import Path

from atlas_core.controller import AtlasController
from atlas_core.evaluator import evaluate
from atlas_core.evidence import findings_in, observed_sources
from atlas_core.planner import build_plan
from atlas_core.router import select_route

ROOT = Path(__file__).parents[1]

REPO_TASK = "granska repo och hitta P0 P1 P2 förbättringar"

# A real filesystem-adapter observation: "<relpath>:\n<content head>".
README_OBS = "README.md:\n# Demo repo\n\nEtt litet repo."
PYPROJECT_OBS = "pyproject.toml:\n[project]\nname = 'demo'"

# What mqobsidian emits. Durable memory is explicitly not runtime truth, so it
# must not be usable as evidence for a claim about the repo as it is now.
MEMORY_OBS = (
    "Durable memory (not runtime truth; verify current claims in source)\n"
    "memory/context-cards/demo-card.md:\n# Demo card"
)


def _repo_plan():
    return build_plan(REPO_TASK, select_route(REPO_TASK))


def _evaluate(output, observations, iteration=1, max_iterations=2):
    plan = _repo_plan()
    return evaluate(
        REPO_TASK,
        output,
        plan.validation_focus,
        iteration,
        max_iterations,
        route_name=plan.route_name,
        observations=observations,
    )


class TestObservedSources(unittest.TestCase):
    def test_extracts_the_path_label_from_an_observation(self):
        self.assertEqual(observed_sources([README_OBS, PYPROJECT_OBS]), ["README.md", "pyproject.toml"])

    def test_prose_observations_are_not_sources(self):
        self.assertEqual(observed_sources(["Local repo path: /tmp/demo"]), [])
        self.assertEqual(observed_sources(["Repo path not found: /tmp/nope"]), [])

    def test_durable_memory_is_not_a_verifiable_source(self):
        """docs/safety-model.md: memory is context, not current runtime truth."""
        self.assertEqual(observed_sources([MEMORY_OBS]), [])

    def test_findings_are_read_from_the_named_headings_only(self):
        output = (
            "# R\n\n## Review method\n- inte ett fynd\n\n"
            "## Verified findings\n- `README.md` saknar installationssteg\n- till\n\n"
            "## Next step\n- inte heller ett fynd\n"
        )
        self.assertEqual(
            findings_in(output, ("## Verified findings",)),
            ["`README.md` saknar installationssteg", "till"],
        )


class TestEvidenceGate(unittest.TestCase):
    def test_wellformatted_repo_review_without_sources_cannot_pass(self):
        """DoD 1. The old evaluator passed this output at 0.9."""
        state = AtlasController(max_iterations=2).run(REPO_TASK, json_mode=True)
        evaluation = state["evaluations"][-1]

        self.assertFalse(evaluation["passed"])
        self.assertIn("no_sources_observed", evaluation["evidence_gaps"])
        self.assertEqual(state["status"], "done")

    def test_no_sources_is_not_an_actionable_retry(self):
        """P1: stop if the gap cannot be fixed with the available sources.

        Another pass over the same empty observation list cannot cite anything,
        so burning the second iteration on it would be theatre.
        """
        state = AtlasController(max_iterations=2).run(REPO_TASK, json_mode=True)

        self.assertEqual(state["iteration"], 1)
        self.assertEqual(state["stop_reason"], "no_actionable_retry")
        self.assertFalse(state["evaluations"][-1]["should_retry"])

    def test_uncited_finding_is_marked_unverified(self):
        """DoD 2."""
        output = (
            "# Repo Review\n\n## Verified findings\n"
            "- Repoet saknar tester\n"
            "- `README.md` saknar installationssteg\n\n"
            "## Recommendation\nx\n\n## Next step\ny\n\n## Confidence\nLow.\n"
        )
        evaluation = _evaluate(output, [README_OBS])

        self.assertEqual(evaluation.unverified_claims, ["Repoet saknar tester"])
        self.assertEqual(evaluation.evidence_coverage, 0.5)
        self.assertIn("uncited_findings", evaluation.evidence_gaps)

    def test_a_finding_citing_an_observed_file_is_verified(self):
        output = (
            "# Repo Review\n\n## Verified findings\n"
            "- `README.md` saknar installationssteg\n\n"
            "## Recommendation\nx\n\n## Next step\ny\n\n## Confidence\nLow.\n"
        )
        evaluation = _evaluate(output, [README_OBS])

        self.assertEqual(evaluation.unverified_claims, [])
        self.assertEqual(evaluation.evidence_coverage, 1.0)
        self.assertEqual(evaluation.evidence_gaps, [])

    def test_a_finding_citing_durable_memory_is_still_unverified(self):
        output = (
            "# Repo Review\n\n## Verified findings\n"
            "- `memory/context-cards/demo-card.md` säger att repot är klart\n\n"
            "## Recommendation\nx\n\n## Next step\ny\n\n## Confidence\nLow.\n"
        )
        evaluation = _evaluate(output, [MEMORY_OBS])

        self.assertFalse(evaluation.passed)
        self.assertIn("no_sources_observed", evaluation.evidence_gaps)

    def test_evaluator_explains_why_another_iteration_is_needed(self):
        """DoD 3."""
        output = (
            "# Repo Review\n\n## Review method\n- metod, inget fynd\n\n"
            "## Recommendation\nx\n\n## Next step\ny\n\n## Confidence\nLow.\n"
        )
        evaluation = _evaluate(output, [README_OBS])

        self.assertTrue(evaluation.should_retry)
        self.assertIn("no_findings_cited", evaluation.evidence_gaps)
        adjustment = evaluation.suggested_adjustment
        self.assertIsNotNone(adjustment)
        assert adjustment is not None  # narrows for the type checker
        self.assertIn("README.md", adjustment)

    def test_formatting_check_remains_a_separate_secondary_signal(self):
        """P1: keep formatting checks, but do not confuse them for evidence."""
        output = "# Repo Review\n\n## Verified findings\n- `README.md` saknar installationssteg\n"
        evaluation = _evaluate(output, [README_OBS])

        self.assertEqual(evaluation.evidence_gaps, [])
        self.assertEqual(
            sorted(evaluation.missing_sections), ["confidence", "next_step", "recommendation"]
        )


class TestJustifiedSecondIteration(unittest.TestCase):
    """P3's Definition of Done: a second iteration that improves the result.

    Every other retry test in this suite calls execute_plan() or evaluate()
    directly. This one drives the whole controller.
    """

    def test_second_iteration_adds_evidence_and_improves_the_result(self):
        state = AtlasController(max_iterations=2).run(
            REPO_TASK, observations=[README_OBS, PYPROJECT_OBS], json_mode=True
        )

        self.assertEqual(state["iteration"], 2, "the loop must take the second pass")
        first, second = state["evaluations"]

        # The first pass names a gap it can actually close, and says so.
        self.assertIn("no_findings_cited", first["evidence_gaps"])
        self.assertTrue(first["should_retry"])
        self.assertFalse(first["passed"])

        # The second pass closes it with the sources it was actually given.
        self.assertEqual(second["evidence_gaps"], [])
        self.assertEqual(second["evidence_coverage"], 1.0)
        self.assertTrue(second["passed"])
        self.assertEqual(state["stop_reason"], "passed")

        # "Improves the result" must mean the output changed, not just the score.
        self.assertGreater(second["quality_score"], first["quality_score"])
        self.assertNotIn("## Verified findings", state["outputs"][0])
        self.assertIn("## Verified findings", state["outputs"][1])

        # And the new evidence is the observed files, cited by name.
        final = state["outputs"][1]
        self.assertIn("README.md", final.split("## Verified findings", 1)[1])
        self.assertIn("pyproject.toml", final.split("## Verified findings", 1)[1])

    def test_the_retry_does_not_claim_more_than_it_read(self):
        """A verified finding may assert that a file was read, nothing more."""
        state = AtlasController(max_iterations=2).run(
            REPO_TASK, observations=[README_OBS], json_mode=True
        )
        section = state["outputs"][-1].split("## Verified findings", 1)[1]

        self.assertNotIn("pyproject.toml", section)
        self.assertIn("observerad", section.lower())


class TestOtherRoutesUnchanged(unittest.TestCase):
    """The evidence contract is per task type. Only repo_review has one."""

    OTHER_ROUTES = {
        "architecture_decision": "bygg målarkitektur för säker AI-assistent med Zero Trust",
        "root_cause": "hitta grundorsaken till varför releaseflödet fastnar",
        "decision_tradeoff": "jämför tre alternativ och rekommendera väg",
        "learning": "förklara hur det funkar som nybörjare",
        "prompt_improvement": "förbättra prompt för router",
        "general": "hej",
    }

    def test_routes_without_an_evidence_contract_still_pass_on_the_first_pass(self):
        for name, task in self.OTHER_ROUTES.items():
            with self.subTest(route=name):
                state = AtlasController(max_iterations=2).run(task, json_mode=True)
                evaluation = state["evaluations"][-1]

                self.assertEqual(state["route"]["name"], name)
                self.assertTrue(evaluation["passed"])
                self.assertEqual(state["iteration"], 1)
                self.assertEqual(evaluation["evidence_gaps"], [])
                self.assertIsNone(evaluation["evidence_coverage"])


class TestEvidenceFieldsAreDeclared(unittest.TestCase):
    def test_new_fields_are_in_the_evaluation_schema(self):
        schema = json.loads(
            (ROOT / "schemas" / "atlas-evaluation.v1.json").read_text(encoding="utf-8")
        )
        properties = schema["properties"]

        for name in ("evidence_gaps", "unverified_claims", "evidence_coverage"):
            self.assertIn(name, properties, f"{name} must be declared; the schema is closed")

        # 1.x compatibility: new fields are optional, old ones stay required.
        self.assertNotIn("evidence_gaps", schema["required"])
        self.assertIn("missing_sections", schema["required"])


if __name__ == "__main__":
    unittest.main()
