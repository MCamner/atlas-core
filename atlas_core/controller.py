from __future__ import annotations
from typing import Any, Callable, Literal, Mapping, overload
import json

from .state import AtlasEvaluation, AtlasRunState, retry_class
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
from .snapshot import DriftReport, detect_drift
from .observation import Observation
from .observer import (
    ObservationRefused,
    Observer,
    merge_observations,
    request_from,
)
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


def _same_failure(current: AtlasEvaluation, previous: AtlasEvaluation) -> bool:
    """Whether two passes failed in the same way, not merely with the same text.

    Compared on what a next pass would be told to do and on what is still
    unsupported — the action, the gaps it addresses, and the claims that did
    not survive. The quality score and the prose are deliberately not part of
    it: a score that moves by a rounding step while every gap stands is not
    progress, and wording is not a failure.
    """
    return (
        _failure_signature(current) == _failure_signature(previous)
        and current.next_action is not None
    )


def _material_signature(state: AtlasRunState) -> tuple[Any, ...]:
    """What this run has to work with, as a value two iterations can compare.

    ROADMAP.md P1.1 box four calls it the *underlag*: the bytes the run holds
    and the plan it holds them for. Two channels, because those are the two
    that exist —

    - the evidence base, by source and content digest. A new observation
      changes it, a superseded one changes it, and a test result changes it
      too: a test reaches a run as an observation through its own adapter, not
      as a separate kind of thing;
    - the review plan's question and the sources it asks for. A plan that
      narrowed differently is a different investigation, and this is what makes
      "a documented plan change" a fact in the document rather than a claim
      about intent.

    Deliberately not the outputs or the prose context. A producer rewording
    itself is not new material, which is the whole point of the rule.
    """
    base = state.evidence_base
    observations = (
        tuple(sorted((o.source_id, o.content_sha256) for o in base.observations))
        if base is not None
        else ()
    )
    review = getattr(state.plan, "review", None) if state.plan is not None else None
    plan = (
        (review.snapshot_id, review.topic, tuple(review.patterns))
        if review is not None
        else ()
    )
    return (observations, plan)


def _failure_signature(evaluation: AtlasEvaluation) -> tuple[Any, ...]:
    action = evaluation.next_action
    return (
        action.kind if action else None,
        tuple(sorted(action.gap_codes)) if action else (),
        tuple(sorted(evaluation.missing_sections)),
        tuple(sorted(evaluation.evidence_gaps)),
        tuple(sorted(evaluation.unverified_claims)),
    )


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
        observer: Observer | None = ...,
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
        observer: Observer | None = ...,
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
        observer: Observer | None = ...,
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
        observer: Observer | None = None,
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
        # Same rule, same reason: a host read that no quota or deadline covers
        # is an unmetered read path, and P0.3 has none.
        if observer is not None and limits is None:
            raise ValueError("An observer requires RunLimits; no unmetered host reads")
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

        def drift_report() -> DriftReport | None:
            """Whether the state this run read has moved. No decision, no stop.

            Split from the stop so an observation round can sit between the two:
            since P1.1 a drifted run is not necessarily over, because the host
            may be able to read again. The check itself is unchanged.
            """
            base = state.evidence_base
            if base is None or base.is_empty():
                return None
            report = detect_drift(base.snapshot, base.observations)
            return None if report.is_consistent() else report

        def stop_for_drift(report: DriftReport) -> None:
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
            assert base is not None  # only called with a report, which needs one
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

        def read_again(
            evaluation: AtlasEvaluation,
            report: DriftReport | None,
            review: Any = None,
        ) -> str:
            """Ask the host to read the sources this run cannot stand behind.

            Returns what happened, as a word the caller branches on:
            `"new"` when the round changed what can be checked, `"nothing"`
            when it did not, and `"stopped"` when the round ended the run.

            Everything that makes an observation evidence has to survive being
            acquired this way, so the rules live in `observer.merge_observations`
            and the failures land here:

            - a host that raises is `tool_error`. A timeout or an unreachable
              source is the machinery failing, and the state machine already
              says a runtime ending is not a verdict about an answer;
            - an observation bound to another snapshot is refused the same way.
              A run that mixed two states could not say which bytes backed a
              claim, and asking the host for more evidence must not become the
              way around the rule that forbids it;
            - a budget or a cancellation keeps its own reason, because a limit
              is a control stop and the machinery did not fail.

            Nothing here can reach the evaluator. A failed round produces no
            observation, so it cannot become a finding.
            """
            base = state.evidence_base
            assert base is not None and budget is not None  # guarded at the call
            action = evaluation.next_action
            asked_for_by_finding = action is not None and action.kind == "observe_again"
            # Why the run cannot stand behind its sources, from whichever of the
            # two found it. A finding that failed names its statuses; drift that
            # no finding cited names the verification results instead.
            if asked_for_by_finding and action is not None:
                blocked_by = [str(code) for code in action.details.get("blocked_by", [])]
                claims = [str(claim) for claim in (action.details.get("claims") or [])]
            else:
                blocked_by = sorted(
                    {v.result for v in report.not_evidence.values()} if report else set()
                )
                claims = []
            # A first read has no paths to name, only the patterns the plan
            # asked for. A re-read has both: the paths that went stale, and
            # whatever the plan is still waiting on.
            action = evaluation.next_action
            patterns = (
                [str(p) for p in action.details.get("patterns", [])]
                if action is not None
                else []
            )
            request = request_from(
                base.snapshot,
                base.observations,
                blocked_by,
                claims,
                state.iteration,
                patterns=patterns,
                question=review.question if review is not None else "",
            )
            state.enter("observing")
            try:
                budget.check()
                incoming = observer.observe(request)  # type: ignore[union-attr]
                merged, round_result = merge_observations(
                    base.snapshot, base.observations, list(incoming)
                )
            except RunCancelled:
                state.stop("cancelled")
                return "stopped"
            except BudgetExceeded as exc:
                state.metadata["budget_exhausted"] = str(exc)
                state.stop("budget_exhausted")
                return "stopped"
            except Exception as exc:
                state.stop("tool_error")
                state.metadata["failure"] = {
                    "stage": "observer",
                    "error": type(exc).__name__,
                    "message": str(exc)[:MAX_FAILURE_MESSAGE],
                }
                return "stopped"

            already_resolved = {
                pattern
                for previous in state.metadata.get("observation_rounds", [])
                for pattern in previous.get("patterns", [])
            }
            newly_resolved = [
                pattern for pattern in patterns if pattern not in already_resolved
            ]

            record = round_result.to_dict()
            record["iteration"] = state.iteration
            # What the host was asked to resolve. A pattern it came back from
            # is answered even when it found nothing: that is the run learning
            # the repository has no such file, which it cannot learn any other
            # way without listing directories itself.
            record["patterns"] = list(patterns)
            state.metadata.setdefault("observation_rounds", []).append(record)
            if not round_result.has_new_material and not newly_resolved:
                # Rule three. The host answered and nothing it returned changes
                # what the run can check, so another pass would grade the same
                # evidence and fail the same way.
                #
                # A round that resolved a pattern for the first time is the
                # exception, and it is not a loophole: the run learned that
                # the repository has no such file, which is knowledge it had
                # no other way to get. It can only happen once per pattern,
                # because the pattern is recorded as resolved and the gap that
                # asked for it closes.
                return "nothing"

            state.evidence_base = base.with_observations(merged)
            fresh: list[Observation] = list(round_result.added) + [
                observation
                for observation in merged
                if observation.source_id
                in {item.source_id for item in round_result.superseded}
            ]
            try:
                for observation in fresh:
                    # The prose channel is how a producer learns what is now
                    # available; the evidence base is what gets checked. Both
                    # are needed, and they stay separate: this text is context,
                    # and nothing turns it back into an observation.
                    context = f"{observation.path}:\n{observation.excerpt}"
                    budget.charge_output(context)
                    state.observations.append(context)
            except RunCancelled:
                state.stop("cancelled")
                return "stopped"
            except BudgetExceeded as exc:
                state.metadata["budget_exhausted"] = str(exc)
                state.stop("budget_exhausted")
                return "stopped"
            return "new"

        #: One material signature per graded pass, in order. See
        #: `_material_signature` for what counts as material and why.
        materials: list[tuple[Any, ...]] = []

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
            # The plan binds to the state the run carries. It does not go and
            # take a snapshot: taking one is reading, and reading is the
            # host's. A run with no evidence base has no state to review, and
            # the plan says so by carrying no review at all.
            plan = build_plan(
                task,
                route,
                state.evidence_base.snapshot.snapshot_id
                if state.evidence_base
                else None,
            )
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
                review=plan.review,
                resolved_patterns=[
                    pattern
                    for round_record in state.metadata.get("observation_rounds", [])
                    for pattern in round_record.get("patterns", [])
                ],
                # Whether a machine-readable findings block was asked for. It
                # cannot be read off the output: a producer that was asked and
                # wrote none, and one that was asked for nothing and honestly
                # claims nothing, produce the same text. Only the adapter that
                # sent the schema knows, so it records it and this reads it.
                structured_output_required=(
                    state.metadata.get("model_result", {})
                    .get("metadata", {})
                    .get("output_schema_sent")
                    == "true"
                ),
            )
            state.evaluations.append(evaluation)
            # Recorded next to the evaluation it belongs with, so "unchanged
            # feedback" and "unchanged material" are read off the same pass.
            materials.append(_material_signature(state))
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
            report = drift_report()
            # Rule two: a run whose ground moved is not necessarily over. When
            # a host can read again, it is asked before the run is stopped —
            # that is the whole point of the round. Without an observer, or
            # when the round brings nothing new, the stop below is the one this
            # loop has always taken.
            if (
                observer is not None
                and state.evidence_base is not None
                and not evaluation.passed
                and not evaluation.requires_user_approval
                and state.iteration < state.max_iterations
                and (
                    report is not None
                    or (
                        evaluation.next_action is not None
                        and evaluation.next_action.kind == "observe_again"
                    )
                )
            ):
                outcome = read_again(evaluation, report, plan.review)
                if outcome == "stopped":
                    break
                if outcome == "new":
                    state.enter("replanning")
                    continue
            if report is not None:
                stop_for_drift(report)
                break
            # Box four, first half. The action asks for material this run does
            # not hold, and nothing brought any: either no host is attached, or
            # the round above came back with nothing new. Feedback cannot
            # produce bytes, so another pass would grade the same evidence and
            # fail in the same way. Reaching here is already past `read_again`,
            # which is where a host that *can* help gets its chance.
            #
            # `blocked` rather than `no_progress`, for the reason the
            # observation round already uses it: the run did not run out of
            # things to try, it ran out of things it may do for itself.
            outstanding = evaluation.next_action
            if (
                outstanding is not None
                and retry_class(outstanding.kind) == "investigation"
                and not evaluation.passed
                and not evaluation.requires_user_approval
            ):
                state.metadata["blocked"] = {
                    "reason": "no_new_material",
                    "action": outstanding.kind,
                    "gap_codes": list(outstanding.gap_codes),
                    "actor": outstanding.actor,
                    "iteration": state.iteration,
                    "observer_attached": observer is not None,
                }
                state.stop("blocked")
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
            # The same rule stated on the failure rather than on the bytes.
            # A producer can reword an answer, fail in exactly the same way and
            # buy another iteration with nothing; byte equality does not see
            # that, and the feedback it would receive next is the feedback it
            # has already had.
            #
            # Every run, budgeted or not. #29 put it behind a budget because it
            # was a cost rule: another call costs money, so stop paying for a
            # failure already had. Stated as a contract rule it does not depend
            # on anyone counting — a producer that has been told this and
            # answered it has answered it, and the next pass would deliver the
            # same feedback over the same material. The byte-equality rule
            # above stays bounded-runs-only, because that one *is* about cost.
            if (
                len(state.evaluations) >= 2
                and _same_failure(state.evaluations[-1], state.evaluations[-2])
                and evaluation.retry_is_possible
                and not evaluation.blocked_by
            ):
                state.metadata["no_progress"] = {
                    "reason": "unchanged_feedback",
                    "iterations": [state.iteration - 1, state.iteration],
                    "action": (
                        evaluation.next_action.kind if evaluation.next_action else None
                    ),
                    # Whether the run also had nothing new to work from. Both
                    # together are the case box four names; unchanged feedback
                    # on its own is already enough, because the producer has
                    # been told this and has answered it.
                    "material": (
                        "unchanged"
                        if len(materials) >= 2 and materials[-1] == materials[-2]
                        else "changed"
                    ),
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
