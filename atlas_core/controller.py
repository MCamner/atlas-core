from __future__ import annotations
from typing import Any, Literal, overload

from .state import AtlasRunState
from .router import select_route
from .planner import build_plan
from .executor import execute_plan
from .evaluator import evaluate
from .finalizer import finalize
from .memory import build_memory_candidate, save_local_memory
from .safety import safety_notice
from .adapters.model import ModelAdapter, ModelResult
from .adapters.base import MemoryAdapter
from .evidence_base import EvidenceBase
from .machine import classify_stop

# Provider messages are unbounded and may embed request content, so the run
# record keeps a bounded excerpt rather than whatever the provider returned.
MAX_FAILURE_MESSAGE = 512


def _check_model_result(result: object) -> None:
    """Reject a result that does not meet the adapter contract.

    A malformed result must fail the run rather than pass through as output. A
    provider returning None or an empty string is not a cheap success.
    """
    if not isinstance(result, ModelResult):
        raise TypeError(
            f"ModelAdapter.execute must return ModelResult, got {type(result).__name__}"
        )
    if not isinstance(result.output, str) or not result.output.strip():
        raise ValueError("ModelAdapter.execute returned empty output")


class AtlasController:
    def __init__(
        self,
        max_iterations: int = 2,
        memory_dir: str | None = None,
        model_adapter: ModelAdapter | None = None,
        memory_adapter: MemoryAdapter | None = None,
    ):
        if (
            isinstance(max_iterations, bool)
            or not isinstance(max_iterations, int)
            or max_iterations < 1
        ):
            raise ValueError("max_iterations must be a positive integer")
        self.max_iterations = max_iterations
        self.memory_dir = memory_dir
        self.model_adapter = model_adapter
        self.memory_adapter = memory_adapter

    @overload
    def run(
        self,
        task: str,
        *,
        observations: list[str] | None = ...,
        evidence: EvidenceBase | None = ...,
        json_mode: Literal[False] = ...,
    ) -> str: ...

    @overload
    def run(
        self,
        task: str,
        *,
        observations: list[str] | None = ...,
        evidence: EvidenceBase | None = ...,
        json_mode: Literal[True],
    ) -> dict[str, Any]: ...

    @overload
    def run(
        self,
        task: str,
        *,
        observations: list[str] | None = ...,
        evidence: EvidenceBase | None = ...,
        json_mode: bool,
    ) -> str | dict[str, Any]: ...

    def run(
        self,
        task: str,
        *,
        observations: list[str] | None = None,
        evidence: EvidenceBase | None = None,
        json_mode: bool = False,
    ) -> str | dict[str, Any]:
        """Run the loop.

        `observations` is prose context; `evidence` is verifiable sources. They
        are separate parameters because they are separate things, and passing
        the first never produces the second. A run given an evidence base is
        graded by deterministic citation checking; a run without one keeps the
        citation-only grading it always had.
        """
        state = AtlasRunState(task=task, max_iterations=self.max_iterations)
        state.enter("observing")
        # Copy: the caller's list must not grow as a side effect of a run.
        state.observations.extend(list(observations or []))
        state.evidence_base = evidence
        if self.memory_adapter:
            state.observations.extend(self.memory_adapter.read(task))
        notice = safety_notice(task)
        if notice:
            # A warning is not a source, so it stays out of the observation list
            # the executor renders under "Sources inspected".
            state.metadata["safety_notice"] = notice

        while state.iteration < state.max_iterations:
            state.iteration += 1
            state.enter("routing")
            route = select_route(task)
            state.route = route
            state.enter("planning")
            plan = build_plan(task, route)
            state.plan = plan
            state.enter("executing")
            # The previous evaluation is what makes a retry a replan rather than
            # a rerun: it tells the executor which gaps to close this time.
            feedback = state.evaluations[-1] if state.evaluations else None
            if self.model_adapter:
                try:
                    model_result = self.model_adapter.execute(
                        task=task,
                        route=route,
                        plan=plan,
                        observations=state.observations,
                        feedback=feedback,
                    )
                    _check_model_result(model_result)
                except Exception as exc:
                    # A provider that fails is a terminal state, not a crash and
                    # not a silent fallback to the rule-based executor. Falling
                    # back would report an answer the caller did not ask for as
                    # though the model had produced it.
                    state.stop("tool_error")
                    state.metadata["failure"] = {
                        "stage": "model_adapter",
                        "error": type(exc).__name__,
                        "message": str(exc)[:MAX_FAILURE_MESSAGE],
                    }
                    break
                output = model_result.output
                state.metadata["model_result"] = {
                    "provider": model_result.provider,
                    "model": model_result.model,
                    "metadata": model_result.metadata,
                }
            else:
                output = execute_plan(task, plan, state.observations, feedback=feedback)
            state.outputs.append(output)
            state.enter("evaluating")
            evaluation = evaluate(
                task,
                output,
                plan.validation_focus,
                state.iteration,
                state.max_iterations,
                route_name=route.name,
                observations=state.observations,
                evidence_base=state.evidence_base,
            )
            state.evaluations.append(evaluation)
            if (
                evaluation.requires_user_approval
                or evaluation.passed
                or not evaluation.should_retry
            ):
                # One table decides, from what the evaluation found. The
                # earlier version chose between two reasons here on
                # `missing_sections`, which meant a run that exhausted its
                # iterations on an evidence gap reported that it had nothing
                # left to try — while the gap it had was exactly something
                # another pass could have acted on.
                state.stop(
                    classify_stop(
                        passed=evaluation.passed,
                        requires_approval=evaluation.requires_user_approval,
                        blocked_by=evaluation.blocked_by,
                        evidence_gaps=evaluation.evidence_gaps,
                        retry_is_possible=evaluation.retry_is_possible,
                        iterations_left=state.iteration < state.max_iterations,
                    )
                )
                break
            state.enter("replanning")

        if state.stop_reason is None:
            # The loop condition is the only other way out, so reaching here
            # means the iteration bound ended the run. A run that fell out
            # without a reason used to report `null`, which tells a caller
            # nothing about whether it may trust the answer.
            state.stop("max_iterations")

        if state.evaluations:
            candidate = build_memory_candidate(
                task=state.task,
                route_name=state.route.name if state.route else "unknown",
                output=state.outputs[-1] if state.outputs else "",
                quality_score=state.evaluations[-1].quality_score,
            )
            if self.memory_adapter:
                saved_path = self.memory_adapter.write(candidate)
            else:
                saved_path = save_local_memory(self.memory_dir, candidate)
            if saved_path:
                candidate["saved_path"] = saved_path
            state.memory_candidates.append(candidate)
        return finalize(state, json_mode=json_mode)
