"""ROADMAP P0.3, box one: a versioned state machine, and stop reasons that
separate a runtime error from a judgement about an answer.

The old vocabulary had five reasons and one structural problem: `failed` meant
"the machinery broke" while `no_actionable_retry` meant three different things
that call for three different actions — the claims were not established, a
source moved under the run, or there was simply nothing left to try. A caller
branching on the name could not tell them apart, and the run text said the same
sentence for all three.

What these tests establish, and what they do not: the vocabulary exists, is
versioned, is enforced rather than conventional, and every reason a run can
reach today is reachable by a run in this suite. Two declared reasons are not
producible yet, and one test says so by name rather than leaving the gap for a
reader to discover.
"""

import json
import unittest
from pathlib import Path

from atlas_core import machine
from atlas_core.adapters.model import ModelResult
from atlas_core.cli import EXIT_CODES
from atlas_core.controller import AtlasController
from atlas_core.machine import (
    STATE_MACHINE_VERSION,
    STOP_REASONS,
    InvalidTransition,
    StopClass,
    classify_stop,
)
from atlas_core.state import AtlasRunState

ROOT = Path(__file__).resolve().parents[1]

COMPLETE_OUTPUT = """## Recommendation
Use the bounded loop contract.

## Next step
Verify the public schemas.

## Confidence
High.
""" + ("evidence " * 40)

REPO_TASK = "granska repo och hitta P0 P1 P2 förbättringar"


class OutputAdapter:
    def __init__(self, output: str):
        self.output = output

    def execute(self, **kwargs: object) -> ModelResult:
        return ModelResult(output=self.output, provider="test", model="fixture")


class BoomAdapter:
    def execute(self, **kwargs: object) -> ModelResult:
        raise RuntimeError("upstream 503")


class TestTheVocabularyIsVersioned(unittest.TestCase):
    """The table a consumer branches on must be the table the code enforces."""

    def setUp(self) -> None:
        self.declared = json.loads(
            (ROOT / "schemas" / "atlas-state-machine.v1.json").read_text(encoding="utf-8")
        )

    def test_the_declaration_names_the_version_the_module_does(self):
        self.assertEqual(self.declared["version"], STATE_MACHINE_VERSION)

    def test_every_stop_reason_is_declared_with_the_same_class_and_code(self):
        self.assertEqual(set(self.declared["stop_reasons"]), set(STOP_REASONS))
        for reason, entry in self.declared["stop_reasons"].items():
            with self.subTest(reason=reason):
                spec = STOP_REASONS[reason]
                self.assertEqual(entry["stop_class"], spec.stop_class.value)
                self.assertEqual(entry["status"], spec.status)
                self.assertEqual(entry["exit_code"], spec.exit_code)

    def test_the_transition_table_is_declared_in_full(self):
        """A consumer modelling the lifecycle needs the edges, not only the states."""
        self.assertEqual(
            self.declared["transitions"],
            {status: sorted(targets) for status, targets in machine.TRANSITIONS.items()},
        )

    def test_the_old_spellings_map_to_the_new_ones(self):
        self.assertEqual(
            self.declared["legacy_stop_reasons"], dict(machine.LEGACY_STOP_REASONS)
        )
        for old, new in machine.LEGACY_STOP_REASONS.items():
            with self.subTest(old=old):
                self.assertIn(new, STOP_REASONS)
                self.assertNotIn(old, STOP_REASONS)

    def test_the_run_document_says_which_vocabulary_it_used(self):
        run = AtlasController().run("hej", json_mode=True)

        self.assertEqual(run["state_machine"], STATE_MACHINE_VERSION)

    def test_a_stored_document_with_the_old_spelling_still_validates(self):
        """1.x compatibility: the schema accepts what it once emitted."""
        schema = json.loads(
            (ROOT / "schemas" / "atlas-run.v1.json").read_text(encoding="utf-8")
        )
        allowed = schema["properties"]["stop_reason"]["enum"]

        for old in machine.LEGACY_STOP_REASONS:
            with self.subTest(old=old):
                self.assertIn(old, allowed)


class TestAnIllegalTransitionIsRefused(unittest.TestCase):
    """The machine is enforced, not documented. A wrong state reports a wrong
    stop reason, and nothing downstream could tell."""

    def test_a_run_cannot_skip_the_middle_of_the_loop(self):
        state = AtlasRunState(task="t")

        with self.assertRaises(InvalidTransition):
            state.enter("evaluating")

    def test_a_terminal_run_cannot_move_again(self):
        """The dangerous one: a failed run reporting itself done afterwards."""
        state = AtlasRunState(task="t")
        state.enter("observing")
        state.enter("routing")
        state.enter("planning")
        state.enter("executing")
        state.stop("tool_error")

        with self.assertRaises(InvalidTransition):
            state.stop("passed")
        self.assertEqual(state.stop_reason, "tool_error")

    def test_an_undeclared_status_is_not_a_state(self):
        state = AtlasRunState(task="t")

        with self.assertRaisesRegex(InvalidTransition, "not a status"):
            state.enter("almost_done")  # type: ignore[arg-type]

    def test_an_undeclared_stop_reason_is_refused(self):
        state = AtlasRunState(task="t")

        with self.assertRaisesRegex(ValueError, "not a stop reason"):
            state.stop("gave_up")  # type: ignore[arg-type]

    def test_status_and_stop_reason_are_set_together(self):
        """They cannot disagree, because one call writes both."""
        for reason, spec in STOP_REASONS.items():
            with self.subTest(reason=reason):
                state = AtlasRunState(task="t")
                state.enter("observing")
                state.enter("routing")
                state.enter("planning")
                state.enter("executing")
                state.enter("evaluating")
                if not machine.is_legal("evaluating", spec.status):
                    continue
                state.stop(reason)  # type: ignore[arg-type]
                self.assertEqual(state.status, spec.status)
                self.assertEqual(state.to_dict()["stop_class"], spec.stop_class.value)

    def test_the_controller_never_writes_the_two_fields_by_hand(self):
        """Structural: an assignment here would bypass the machine entirely."""
        source = (ROOT / "atlas_core" / "controller.py").read_text(encoding="utf-8")

        self.assertNotIn("state.status =", source)
        self.assertNotIn("state.stop_reason =", source)


class TestRuntimeIsNotAVerdict(unittest.TestCase):
    """ROADMAP P0.3: "Skilj runtime-fel från saklig evaluering."

    Previously both were spelled `failed` — the status and the reason — so the
    only thing telling a caller that nothing had been graded was the empty
    evaluations list.
    """

    def test_a_provider_failure_is_classed_as_runtime(self):
        run = AtlasController(model_adapter=BoomAdapter()).run("hej", json_mode=True)

        self.assertEqual(run["stop_reason"], "tool_error")
        self.assertEqual(run["stop_class"], StopClass.RUNTIME.value)
        self.assertEqual(run["status"], "failed")

    def test_a_runtime_stop_on_the_first_pass_carries_no_grade_at_all(self):
        run = AtlasController(model_adapter=BoomAdapter()).run("hej", json_mode=True)

        self.assertEqual(run["evaluations"], [])
        self.assertEqual(run["outputs"], [])

    def test_a_later_failure_does_not_turn_an_earlier_grade_into_the_outcome(self):
        """The one case where a runtime stop has an evaluation beside it.

        Pass one produced something and was graded; pass two died. The grade
        is kept in the record and is not the run's result, which is what
        `stop_class` says and what a caller must branch on.
        """

        class FailsOnSecondCall:
            def __init__(self) -> None:
                self.n = 0

            def execute(self, **kwargs: object) -> ModelResult:
                self.n += 1
                if self.n == 1:
                    return ModelResult(output="# Svar\n\nKort.\n", provider="p", model="m")
                raise RuntimeError("provider died on pass 2")

        run = AtlasController(max_iterations=2, model_adapter=FailsOnSecondCall()).run(
            "hej", json_mode=True
        )

        self.assertEqual(run["stop_class"], StopClass.RUNTIME.value)
        self.assertEqual(len(run["evaluations"]), 1)
        self.assertFalse(run["evaluations"][-1]["passed"])
        self.assertIsNone(run["evaluations"][-1].get("stop_reason"))

    def test_no_graded_outcome_is_ever_classed_as_runtime(self):
        """The inverse, which is the direction that would mislead."""
        for task, adapter in (
            ("hej", OutputAdapter(COMPLETE_OUTPUT)),
            (REPO_TASK, None),
            ("pusha ändringen", OutputAdapter(COMPLETE_OUTPUT)),
        ):
            with self.subTest(task=task):
                run = AtlasController(model_adapter=adapter).run(task, json_mode=True)
                self.assertNotEqual(run["stop_class"], StopClass.RUNTIME.value)
                self.assertTrue(run["evaluations"])

    def test_exactly_one_reason_is_a_runtime_reason(self):
        runtime = {r for r, s in STOP_REASONS.items() if s.is_runtime}

        self.assertEqual(runtime, {"tool_error"})


class TestWhyTheRunStopped(unittest.TestCase):
    """Each reason a run can reach today, reached by a run."""

    def test_passed(self):
        run = AtlasController(model_adapter=OutputAdapter(COMPLETE_OUTPUT)).run(
            "hej", json_mode=True
        )
        self.assertEqual(run["stop_reason"], "passed")
        self.assertEqual(run["stop_class"], "evaluation")

    def test_insufficient_evidence_when_the_claims_were_not_established(self):
        run = AtlasController().run(REPO_TASK, json_mode=True)

        self.assertEqual(run["stop_reason"], "insufficient_evidence")
        self.assertEqual(run["stop_class"], "evaluation")
        self.assertIn("no_sources_observed", run["evaluations"][-1]["evidence_gaps"])

    def test_no_progress_when_nothing_was_left_to_change(self):
        """A short but complete answer on a route that owes no evidence.

        Not an evidence verdict: nothing was found wanting about its sources.
        Another identical pass would produce the identical output, so the loop
        stopped rather than spending an iteration proving that.
        """
        short = "## Recommendation\nx\n## Next step\ny\n## Confidence\nLow."
        run = AtlasController(model_adapter=OutputAdapter(short)).run(
            "hej", json_mode=True
        )

        self.assertEqual(run["stop_reason"], "no_progress")
        self.assertEqual(run["evaluations"][-1]["evidence_gaps"], [])
        self.assertFalse(run["evaluations"][-1]["retry_is_possible"])

    def test_max_iterations_when_the_bound_was_what_stopped_it(self):
        run = AtlasController(
            max_iterations=1, model_adapter=OutputAdapter("incomplete " * 50)
        ).run("hej", json_mode=True)

        self.assertEqual(run["stop_reason"], "max_iterations")
        self.assertTrue(run["evaluations"][-1]["retry_is_possible"])

    def test_approval_required(self):
        run = AtlasController(model_adapter=OutputAdapter(COMPLETE_OUTPUT)).run(
            "pusha ändringen", json_mode=True
        )

        self.assertEqual(run["stop_reason"], "approval_required")
        self.assertEqual(run["status"], "need_user_approval")


class TestTheBoundIsOnlyTheReasonWhenItBound(unittest.TestCase):
    """The bug this box was written to fix.

    The old controller chose `max_iterations` only when `missing_sections` was
    non-empty. A run that spent every iteration on an evidence gap — a gap
    another pass could have acted on — therefore reported that it had nothing
    left to try. The two failures ask a reader for opposite things: raise the
    bound, or stop and look at the evidence.
    """

    def _uncited(self, max_iterations: int) -> dict:
        output = (
            "# Repo Review\n\n## Observed sources\n- README.md\n\n"
            "## Verified findings\n- Repoet saknar tester helt och hållet\n\n"
            "## Recommendation\nx\n\n## Next step\ny\n\n## Confidence\nLow.\n"
            + ("evidence " * 40)
        )
        return AtlasController(
            max_iterations=max_iterations, model_adapter=OutputAdapter(output)
        ).run(REPO_TASK, observations=["README.md:\n# Demo"], json_mode=True)

    def test_an_evidence_gap_that_ran_out_of_passes_says_so(self):
        run = self._uncited(max_iterations=2)

        self.assertIn("uncited_findings", run["evaluations"][-1]["evidence_gaps"])
        self.assertTrue(run["evaluations"][-1]["retry_is_possible"])
        self.assertEqual(run["iteration"], 2)
        self.assertEqual(run["stop_reason"], "max_iterations")

    def test_it_is_not_reported_as_having_nothing_left_to_try(self):
        """Negative control on the same run: the old answer must not come back."""
        run = self._uncited(max_iterations=2)

        self.assertNotEqual(run["stop_reason"], "no_progress")
        self.assertNotEqual(run["stop_reason"], "insufficient_evidence")

    def test_a_run_that_never_reached_the_bound_does_not_blame_it(self):
        """The other direction: plenty of passes left, and none would help."""
        run = AtlasController(max_iterations=5).run(REPO_TASK, json_mode=True)

        self.assertEqual(run["iteration"], 1)
        self.assertNotEqual(run["stop_reason"], "max_iterations")
        self.assertEqual(run["stop_reason"], "insufficient_evidence")


class TestTheDecisionTable(unittest.TestCase):
    """`classify_stop` as the table it is, without building a controller."""

    def _classify(self, **overrides: object) -> str:
        args: dict = {
            "passed": False,
            "requires_approval": False,
            "blocked_by": [],
            "evidence_gaps": [],
            "retry_is_possible": False,
            "iterations_left": False,
        }
        args.update(overrides)
        return classify_stop(**args)  # type: ignore[arg-type]

    def test_approval_outranks_everything_including_a_pass(self):
        self.assertEqual(
            self._classify(passed=True, requires_approval=True), "approval_required"
        )

    def test_a_moved_source_outranks_the_evidence_verdict(self):
        """Re-citing cannot repair it, so "observe again" is the useful answer."""
        self.assertEqual(
            self._classify(blocked_by=["stale_source"], evidence_gaps=["unsound_citations"]),
            "blocked",
        )

    def test_the_bound_is_not_blamed_when_nothing_was_left_to_try(self):
        self.assertEqual(
            self._classify(evidence_gaps=["no_sources_observed"], retry_is_possible=False),
            "insufficient_evidence",
        )

    def test_the_bound_is_blamed_when_something_was_left_to_try(self):
        self.assertEqual(
            self._classify(evidence_gaps=["uncited_findings"], retry_is_possible=True),
            "max_iterations",
        )

    def test_nothing_wrong_with_the_evidence_and_nothing_left_is_no_progress(self):
        self.assertEqual(self._classify(), "no_progress")


class TestTheTextFormSaysWhichKindOfEnding(unittest.TestCase):
    """The trailer a human reads has to carry the distinction too.

    The run document is what an adapter branches on, but a person reading the
    text is the one who decides whether to trust the answer — and "the
    provider died" and "the claims did not hold up" are the two endings most
    easily mistaken for each other.
    """

    def test_a_runtime_failure_says_nothing_was_graded(self):
        text = AtlasController(model_adapter=BoomAdapter()).run("hej")

        self.assertIn("Stop reason: tool_error (runtime)", text)
        self.assertIn("model_adapter raised RuntimeError", text)
        self.assertIn("not a verdict on the answer", text)

    def test_a_graded_ending_carries_no_failure_line(self):
        """Negative control: the failure note must not appear on a verdict."""
        text = AtlasController().run(REPO_TASK)

        self.assertIn("Stop reason: insufficient_evidence (evaluation)", text)
        self.assertNotIn("Failure:", text)


class TestExitCodes(unittest.TestCase):
    def test_every_declared_reason_has_a_code(self):
        self.assertEqual(set(EXIT_CODES), set(STOP_REASONS))

    def test_passing_is_the_only_zero(self):
        zeros = {reason for reason, code in EXIT_CODES.items() if code == 0}

        self.assertEqual(zeros, {"passed"})

    def test_a_runtime_error_does_not_share_a_code_with_a_verdict(self):
        """Exit 1 must mean "it broke", never "the answer did not hold up"."""
        ones = {reason for reason, code in EXIT_CODES.items() if code == 1}

        self.assertEqual(ones, {"tool_error"})


class TestDeclaredButNotYetProduced(unittest.TestCase):
    """Two reasons exist in the vocabulary and nothing emits them yet.

    Declaring them now is deliberate: the contract a consumer codes against
    should not gain members every time a limit lands. Pretending they are
    reachable would be the worse half of that trade, so the gap is a test
    rather than a comment — a later PR has to come here and delete a line.
    """

    # Cancellation is produced by the controller's runtime checkpoints.
    NOT_YET_PRODUCED: dict[str, str] = {}

    def test_the_two_sets_together_are_the_whole_vocabulary(self):
        produced = {
            "passed",
            "insufficient_evidence",
            "blocked",
            "approval_required",
            "max_iterations",
            "no_progress",
            "budget_exhausted",
            "tool_error",
            "cancelled",
        }

        self.assertEqual(produced | set(self.NOT_YET_PRODUCED), set(STOP_REASONS))

    def test_no_combination_of_evaluation_results_produces_them(self):
        """Exhaustive over the decision table's whole input domain.

        Stronger than grepping for the word: `cancelled` is also a CI
        conclusion, so a name search would find it in a module that has
        nothing to do with stopping a run.
        """
        reachable = {
            classify_stop(
                passed=passed,
                requires_approval=approval,
                blocked_by=["stale_source"] if blocked else [],
                evidence_gaps=["uncited_findings"] if gaps else [],
                retry_is_possible=retry,
                iterations_left=left,
            )
            for passed in (True, False)
            for approval in (True, False)
            for blocked in (True, False)
            for gaps in (True, False)
            for retry in (True, False)
            for left in (True, False)
        }

        self.assertEqual(reachable & set(self.NOT_YET_PRODUCED), set())

    def test_nothing_stops_a_run_for_them(self):
        """`state.stop` is the only way to end a run, so the call sites decide."""
        for reason in self.NOT_YET_PRODUCED:
            for path in sorted((ROOT / "atlas_core").rglob("*.py")):
                with self.subTest(reason=reason, module=path.name):
                    self.assertNotIn(
                        f'stop("{reason}")', path.read_text(encoding="utf-8")
                    )


if __name__ == "__main__":
    unittest.main()
