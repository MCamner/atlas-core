from __future__ import annotations
from typing import Any, Callable, Literal, Mapping, overload
import json

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
from .snapshot import detect_drift
from .budget import BudgetExceeded, RunBudget, RunCancelled, RunLimits
from .tool_gateway import ToolDefinition, ToolGateway

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
    # Explicit JSON contract: malformed provider output is a runtime failure,
    # not prose that the evaluator may accidentally accept.
    if result.metadata.get("format") == "json":
        try:
            json.loads(result.output)
        except json.JSONDecodeError as exc:
            raise ValueError("ModelAdapter.execute returned malformed JSON") from exc


class AtlasController:
    def __init__(
        self,
        max_iterations: int = 2,
        memory_dir: str | None = None,
        model_adapter: ModelAdapter | None = None,
        memory_adapter: MemoryAdapter | None = None,
        tools: Mapping[str, ToolDefinition] | None = None,
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
        self.tools = dict(tools or {})

    @overload
    def run(
        self,
        task: str,
        *,
        observations: list[str] | None = ...,
        evidence: EvidenceBase | None = ...,
        json_mode: Literal[False] = ...,
        limits: RunLimits | None = ...,
        cancelled: Callable[[], bool] | None = ...,
        readers: list[Callable[[str, RunBudget], list[str]]] | None = ...,
    ) -> str: ...

    @overload
    def run(
        self,
        task: str,
        *,
        observations: list[str] | None = ...,
        evidence: EvidenceBase | None = ...,
        json_mode: Literal[True],
        limits: RunLimits | None = ...,
        cancelled: Callable[[], bool] | None = ...,
        readers: list[Callable[[str, RunBudget], list[str]]] | None = ...,
    ) -> dict[str, Any]: ...

    @overload
    def run(
        self,
        task: str,
        *,
        observations: list[str] | None = ...,
        evidence: EvidenceBase | None = ...,
        json_mode: bool,
        limits: RunLimits | None = ...,
        cancelled: Callable[[], bool] | None = ...,
        readers: list[Callable[[str, RunBudget], list[str]]] | None = ...,
    ) -> str | dict[str, Any]: ...

    def run(
        self,
        task: str,
        *,
        observations: list[str] | None = None,
        evidence: EvidenceBase | None = None,
        json_mode: bool = False,
        limits: RunLimits | None = None,
        cancelled: Callable[[], bool] | None = None,
        readers: list[Callable[[str, RunBudget], list[str]]] | None = None,
    ) -> str | dict[str, Any]:
        """Run the loop.

        `observations` is prose context; `evidence` is verifiable sources. They
        are separate parameters because they are separate things, and passing
        the first never produces the second. A run given an evidence base is
        graded by deterministic citation checking; a run without one keeps the
        citation-only grading it always had.
        """
        if self.tools and limits is None:
            raise ValueError("Atlas-managed tools require RunLimits; no unmetered gateway")
        if readers and limits is None:
            raise ValueError("Atlas-managed readers require RunLimits")
        state = AtlasRunState(task=task, max_iterations=self.max_iterations)
        budget = RunBudget(limits, cancelled=cancelled) if limits is not None else None
        gateway = ToolGateway(budget=budget, tools=self.tools) if budget is not None and self.tools else None

        def expired() -> bool:
            try:
                if budget is None:
                    if cancelled is not None and cancelled():
                        raise RunCancelled("cancelled")
                else:
                    budget.check()
            except RunCancelled:
                state.stop("cancelled")
                return True
            except BudgetExceeded as exc:
                state.metadata["budget_exhausted"] = str(exc)
                state.stop("budget_exhausted")
                return True
            return False

        def drifted() -> bool:
            """Stop the run if the state its sources were read from has moved.

            The roadmap's second P0.1 box asks a run to notice a changed HEAD
            or file *during* the read. Two things already existed and were
            never connected to a run: `detect_drift`, which pairs the HEAD
            check with a content check per source, and the stop reason for it.

            What citation checking cannot see is why this is separate. Checking
            a citation re-reads what it points at, so a cited source that moves
            is caught there. Nothing looked at the rest — a branch switched
            mid-run, or a source no finding happened to cite — and a review
            resting on a state that no longer exists is not a weaker answer, it
            is an answer about something else.

            `blocked` rather than a verdict: the ground moved, which is not a
            judgement about the answer. The state machine already says so.

            One gate, after grading, rather than a pre-flight one as well. An
            earlier refusal would save a model call, and it would cost the
            per-finding record that says *which* claim rested on what moved —
            and it would fire or not depending on whether the root happens to
            be a git checkout, since an edit there also flips clean to dirty.
            Grading first keeps one rule and loses nothing: the evaluation is
            history, and the run still ends `blocked`.

            Not separately metered. The gate re-reads exactly the observations
            the caller handed the run, a set fixed before the run starts and
            not one the model or a tool can grow — the same treatment
            caller-supplied prose context gets. The deadline and cancellation
            still apply, through the `expired()` call that precedes each gate.
            """
            base = state.evidence_base
            if base is None or base.is_empty():
                return False
            report = detect_drift(base.snapshot, base.observations)
            if report.is_consistent():
                return False
            by_id = {
                observation.source_id: observation for observation in base.observations
            }
            state.metadata["drift"] = {
                "head_moved": report.head_moved,
                "not_evidence": {
                    source_id: {"result": v.result, "reason": v.reason}
                    for source_id, v in report.not_evidence.items()
                },
                # The paths beside the ids, because a reader who has to act on
                # this needs to know which files to look at, and resolving ids
                # through the manifest to find that out is work the run can do.
                "paths": sorted(
                    by_id[source_id].path
                    for source_id in report.not_evidence
                    if source_id in by_id
                ),
            }
            state.stop("blocked")
            return True

        state.enter("observing")
        # Copy: the caller's list must not grow as a side effect of a run.
        state.observations.extend(list(observations or []))
        state.evidence_base = evidence
        if readers:
            assert budget is not None  # checked at entry: no unmetered readers
            try:
                for reader in readers:
                    budget.check()
                    gathered = reader(task, budget)
                    if not isinstance(gathered, list) or any(
                        not isinstance(item, str) for item in gathered
                    ):
                        raise TypeError("source reader must return list[str]")
                    budget.charge_output("\n".join(gathered))
                    state.observations.extend(gathered)
            except RunCancelled:
                state.stop("cancelled")
            except BudgetExceeded as exc:
                state.metadata["budget_exhausted"] = str(exc)
                state.stop("budget_exhausted")
            except Exception as exc:
                state.stop("tool_error")
                state.metadata["failure"] = {
                    "stage": "observer",
                    "error": type(exc).__name__,
                    "message": str(exc)[:MAX_FAILURE_MESSAGE],
                }
            if state.stop_reason is not None:
                state.metadata["budget_usage"] = budget.usage()
                return finalize(state, json_mode=json_mode)
        # No unmetered reads from host adapters in resource-limited runs.
        if self.memory_adapter and budget is None:
            state.observations.extend(self.memory_adapter.read(task))
        elif self.memory_adapter:
            state.metadata["memory_read_skipped"] = "budgeted_run_has_no_metered_memory_reader"
        notice = safety_notice(task)
        if notice:
            # A warning is not a source, so it stays out of the observation list
            # the executor renders under "Sources inspected".
            state.metadata["safety_notice"] = notice

        if expired():
            if budget is not None:
                state.metadata["budget_usage"] = budget.usage()
            return finalize(state, json_mode=json_mode)
        while state.iteration < state.max_iterations:
            if expired():
                break
            state.iteration += 1
            state.enter("routing")
            route = select_route(task)
            state.route = route
            state.enter("planning")
            plan = build_plan(task, route)
            state.plan = plan
            state.enter("executing")
            if expired():
                break
            # The previous evaluation is what makes a retry a replan rather than
            # a rerun: it tells the executor which gaps to close this time.
            feedback = state.evaluations[-1] if state.evaluations else None
            if self.model_adapter:
                try:
                    kwargs: dict[str, Any] = dict(
                        task=task, route=route, plan=plan,
                        observations=state.observations, feedback=feedback,
                    )
                    if budget is not None:
                        budget.reserve_model()
                        kwargs["budget"] = budget
                    if gateway is not None:
                        kwargs["tools"] = gateway
                    model_result = self.model_adapter.execute(**kwargs)
                    _check_model_result(model_result)
                    if budget is not None:
                        raw_usage = model_result.metadata.get("usage_tokens")
                        usage = int(raw_usage) if isinstance(raw_usage, str) and raw_usage.isdecimal() else None
                        budget.charge_tokens(usage)
                        budget.charge_output(model_result.output)
                except RunCancelled:
                    state.stop("cancelled")
                    break
                except BudgetExceeded as exc:
                    state.metadata["budget_exhausted"] = str(exc)
                    state.stop("budget_exhausted")
                    break
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
            if budget is not None and self.model_adapter is None:
                try:
                    budget.charge_output(output)
                except RunCancelled:
                    state.stop("cancelled")
                    break
                except BudgetExceeded as exc:
                    state.metadata["budget_exhausted"] = str(exc)
                    state.stop("budget_exhausted")
                    break
            state.outputs.append(output)
            state.enter("evaluating")
            if expired():
                break
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
            if expired():
                break
            # The second gate, after grading rather than before it. A provider
            # call is where a run spends its time, so it is where the state is
            # most likely to move — but stopping before the evaluator runs
            # would throw away the per-finding record that says *which* claim
            # rested on what moved, which is what a reader needs in order to
            # act. So the answer is graded, the record is kept, and the run
            # still ends `blocked`: the grade is history, not this run's
            # outcome. It also takes precedence over `approval_required`, since
            # an approval bound to a state that has moved is worse than none.
            if drifted():
                break
            # In bounded runs, two identical unsuccessful model outputs with
            # no new observation establish that another call is unproductive.
            # Legacy unbudgeted verdict semantics remain unchanged.
            if (
                budget is not None
                and self.model_adapter is not None
                and len(state.outputs) >= 2
                and state.outputs[-1] == state.outputs[-2]
                and evaluation.retry_is_possible
                and not evaluation.blocked_by
            ):
                state.metadata["no_progress"] = {
                    "reason": "identical_model_output",
                    "iterations": [state.iteration - 1, state.iteration],
                }
                state.stop("no_progress")
                break
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

        if budget is not None:
            state.metadata["budget_usage"] = budget.usage()
            # The memory writer has no deadline or tool-accounting contract.
            # A budgeted run refuses to call this unmetered side effect.
            state.metadata["memory_skipped"] = "budgeted_run_has_no_metered_memory_writer"
        # Only a passing unbudgeted run may promote a memory candidate.
        if budget is None and state.evaluations and state.stop_reason in {"passed"}:
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
