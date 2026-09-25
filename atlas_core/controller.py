from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from typing import Any, Callable, Iterator, Literal, Mapping, cast, overload
import json
from pathlib import Path

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
from .eventlog import (
    EventLog,
    EventSink,
    JsonlSink,
    ResumeRefused,
    RunLock,
    digest,
    read_jsonl,
    unfinished_calls,
)
from .evidence_base import EvidenceBase
from .host_api import (
    EventLogInUse, RunIdInUse, hold, lock_path, log_holds_a_run, new_run_id,
    validate_run_id, writer_lock_path,
)
from .machine import classify_stop, stop_class_of
from .snapshot import DriftReport, detect_drift
from .observation import Observation
from .observer import (
    ObservationRefused,
    ObservationRequest,
    Observer,
    merge_observations,
    request_from,
)
from .budget import BudgetExceeded, RunBudget, RunCancelled, RunLimits
from .tool_gateway import ToolDefinition, ToolGateway

# Provider messages are unbounded and may embed request content, so the run
# record keeps a bounded excerpt rather than whatever the provider returned.
MAX_FAILURE_MESSAGE = 512
_RESUME_TOKEN = object()


def _evidence_identity(evidence: EvidenceBase | None) -> tuple[str | None, str | None]:
    if evidence is None:
        return None, None
    material = {
        "snapshot_id": evidence.snapshot.snapshot_id,
        "observations": sorted(
            (item.source_id, item.content_sha256) for item in evidence.observations
        ),
    }
    return evidence.snapshot.snapshot_id, digest(material)


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



def _round_material(round_result: Any) -> set[tuple[str, str]]:
    """The (source_id, digest) pairs one round adopted."""
    return {
        (item.source_id, item.content_sha256) for item in round_result.added
    } | {(item.source_id, item.new_sha256) for item in round_result.superseded}


def _logged_round_material(payload: Mapping[str, Any]) -> set[tuple[str, str]]:
    """The same pairs, read back from an `observation_recorded` payload."""
    return {
        (str(item.get("source_id")), str(item.get("sha256")))
        for item in payload.get("added", [])
    } | {
        (str(item.get("source_id")), str(item.get("new_sha256")))
        for item in payload.get("superseded", [])
    }

class AtlasController:
    def __init__(
        self,
        max_iterations: int = 2,
        memory_dir: str | None = None,
        model_adapter: ModelAdapter | None = None,
        memory_adapter: MemoryAdapter | None = None,
        tools: Mapping[str, ToolDefinition] | None = None,
        events: EventSink | None = None,
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
        #: Where the append-only log goes, or `None` for no log. A sink rather
        #: than a log, because a log belongs to one run and the run id does not
        #: exist until the run starts. `None` changes nothing about a run: the
        #: log records what happened, it does not decide anything.
        self.events = events

    def resume(
        self,
        task: str,
        *,
        run_id: str,
        observations: list[str] | None = None,
        evidence: EvidenceBase | None = None,
        json_mode: bool = False,
        limits: RunLimits | None = None,
        cancelled: Callable[[], bool] | None = None,
        readers: list[Callable[[str, RunBudget], list[str]]] | None = None,
        observer: Observer | None = None,
        read_first: bool = False,
    ) -> str | dict[str, Any]:
        """Resume one interrupted read-only run from its durable event log.

        Raw evidence is deliberately not reconstructed from the log. The host
        supplies it again and its snapshot/digest must match `run_started`.
        """
        if not isinstance(self.events, JsonlSink):
            raise ResumeRefused("resume requires a durable JsonlSink")
        if self.memory_adapter is not None or self.memory_dir is not None:
            raise ResumeRefused(
                "resume refuses memory writers because their prior outcome is not logged"
            )
        if not run_id:
            raise ResumeRefused("resume requires a run id")
        with self._writer(), RunLock(lock_path(self.events.path, run_id)):
            return self._resume_locked(
                task,
                run_id=run_id,
                observations=observations,
                evidence=evidence,
                json_mode=json_mode,
                limits=limits,
                cancelled=cancelled,
                readers=readers,
                observer=observer,
                read_first=read_first,
            )

    def _resume_locked(
        self,
        task: str,
        *,
        run_id: str,
        observations: list[str] | None,
        evidence: EvidenceBase | None,
        json_mode: bool,
        limits: RunLimits | None,
        cancelled: Callable[[], bool] | None,
        readers: list[Callable[[str, RunBudget], list[str]]] | None,
        observer: Observer | None,
        read_first: bool,
    ) -> str | dict[str, Any]:
        assert isinstance(self.events, JsonlSink)
        records = [
            record
            for record in read_jsonl(self.events.path)
            if record.get("run_id") == run_id
        ]
        if not records:
            raise ResumeRefused(f"resume log has no run {run_id!r}")
        if any(record.get("kind") == "run_stopped" for record in records):
            raise ResumeRefused("run already stopped and cannot be resumed")
        started = next(
            (record for record in records if record.get("kind") == "run_started"),
            None,
        )
        if started is None:
            raise ResumeRefused("resume log has no run_started event")
        payload = started.get("payload", {})
        if payload.get("task_sha256") != digest(task):
            raise ResumeRefused("task does not match the interrupted run")
        if payload.get("max_iterations") != self.max_iterations:
            raise ResumeRefused("max_iterations does not match the interrupted run")
        if payload.get("observations_sha256") != digest(observations or []):
            raise ResumeRefused("observations do not match the interrupted run")
        snapshot_id, evidence_sha256 = _evidence_identity(evidence)
        if payload.get("snapshot_id") != snapshot_id:
            raise ResumeRefused("evidence snapshot does not match the interrupted run")
        if payload.get("evidence_sha256") != evidence_sha256:
            raise ResumeRefused("evidence does not match the interrupted run")

        unknown = set(unfinished_calls(records))
        unsafe = [
            record.get("call_id")
            for record in records
            if record.get("kind") == "call_started"
            and record.get("call_id") in unknown
            and record.get("payload", {}).get("idempotent") is not True
        ]
        if unsafe:
            raise ResumeRefused(
                "cannot replay an unfinished non-idempotent call: "
                + ", ".join(str(item) for item in unsafe)
            )

        return cast(Any, self.run)(
            task,
            observations=observations,
            evidence=evidence,
            json_mode=json_mode,
            limits=limits,
            cancelled=cancelled,
            readers=readers,
            observer=observer,
            read_first=read_first,
            _resume_records=records,
            _resume_token=_RESUME_TOKEN,
        )

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
        read_first: bool = ...,
        run_id: str | None = ...,
        one_run_per_log: bool = ...,
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
        read_first: bool = ...,
        run_id: str | None = ...,
        one_run_per_log: bool = ...,
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
        read_first: bool = ...,
        run_id: str | None = ...,
        one_run_per_log: bool = ...,
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
        read_first: bool = False,
        run_id: str | None = None,
        one_run_per_log: bool = False,
        _resume_records: list[dict[str, Any]] | None = None,
        _resume_token: object | None = None,
    ) -> str | dict[str, Any]:
        """Run the loop.

        `run_id` lets a host name the run before it exists (v1.4 `create`).
        With a durable `JsonlSink`, a fresh run holds the run's lock for its
        whole life, so `atlas status` can tell a live run from an interrupted
        one, and an id the log already holds is refused before anything is
        written: two runs under one id would be one history nobody can read.

        A durable run also holds the log's writer lock, so a second process
        appending to the same file is refused (`EventLogInUse`) rather than
        interleaved. `one_run_per_log=True` — what the CLI passes — refuses a
        log that already holds any run.
        """
        if run_id is not None:
            validate_run_id(run_id)
        if _resume_records is not None or not isinstance(self.events, JsonlSink):
            return self._run(
                task, observations=observations, evidence=evidence,
                json_mode=json_mode, limits=limits, cancelled=cancelled,
                readers=readers, observer=observer, read_first=read_first, run_id=run_id,
                _resume_records=_resume_records, _resume_token=_resume_token,
            )
        run_id = run_id or new_run_id()
        with self._writer():
            try:
                lock = RunLock(lock_path(self.events.path, run_id)).acquire()
            except ResumeRefused as exc:
                raise RunIdInUse(f"run {run_id!r} is held by a live process") from exc
            try:
                if one_run_per_log and log_holds_a_run(self.events.path):
                    raise EventLogInUse(
                        f"{self.events.path} already holds a run; "
                        "one run per event log"
                    )
                if any(
                    record.get("run_id") == run_id
                    for record in (read_jsonl(self.events.path)
                                   if self.events.path.exists() else [])
                ):
                    raise RunIdInUse(
                        f"run {run_id!r} already exists in {self.events.path}"
                    )
                return self._run(
                    task, observations=observations, evidence=evidence,
                    json_mode=json_mode, limits=limits, cancelled=cancelled,
                    readers=readers, observer=observer, read_first=read_first, run_id=run_id,
                )
            finally:
                lock.release()

    @contextmanager
    def _writer(self) -> Iterator[None]:
        """The log's writer lock, or `EventLogInUse`. One writer per file."""
        assert isinstance(self.events, JsonlSink)
        try:
            lock = hold(writer_lock_path(self.events.path))
        except ResumeRefused as exc:
            raise EventLogInUse(
                f"{self.events.path} is being written by another run"
            ) from exc
        try:
            yield
        finally:
            lock.release()

    def _run(
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
        read_first: bool = False,
        run_id: str | None = None,
        _resume_records: list[dict[str, Any]] | None = None,
        _resume_token: object | None = None,
    ) -> str | dict[str, Any]:
        """The loop itself. `run` decides identity and locking first.

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
        if _resume_records is not None and _resume_token is not _RESUME_TOKEN:
            raise ResumeRefused("resume records may only enter through resume()")
        resumed_run_id = (
            str(_resume_records[0]["run_id"]) if _resume_records is not None else None
        )
        chosen_run_id = resumed_run_id or run_id
        if chosen_run_id is None:
            state = AtlasRunState(task=task, max_iterations=self.max_iterations)
        else:
            state = AtlasRunState(
                task=task,
                run_id=chosen_run_id,
                max_iterations=self.max_iterations,
            )
        # The log is built here because it belongs to one run, and the run id
        # does not exist until now. Absent when no sink was configured, and a
        # run with no log behaves identically — the log records, it decides
        # nothing.
        log = (
            EventLog(state.run_id, self.events, previous=_resume_records or ())
            if self.events is not None
            else None
        )
        if log is not None and _resume_records is None:
            # The digest, not the task. This file persists whether or not
            # anyone exports the run.
            log.append(
                "run_started",
                task_sha256=digest(task),
                max_iterations=state.max_iterations,
                observations_sha256=digest(observations or []),
                snapshot_id=_evidence_identity(evidence)[0],
                evidence_sha256=_evidence_identity(evidence)[1],
            )
        elif log is not None:
            unknown = unfinished_calls(_resume_records or ())
            log.append(
                "interrupted",
                unfinished_calls=unknown,
                detected_after_sequence=len(_resume_records or ()) - 1,
            )
            log.append(
                "resumed",
                replay="read_only_from_start",
                snapshot_id=_evidence_identity(evidence)[0],
            )
        budget = RunBudget(limits, cancelled=cancelled) if limits is not None else None
        #: What each observation round of the interrupted run adopted, in order.
        #: Empty for a fresh run.
        recorded_rounds = [
            _logged_round_material(record["payload"])
            for record in _resume_records or ()
            if record.get("kind") == "observation_recorded"
        ]
        gateway = (
            ToolGateway(budget=budget, tools=self.tools, log=log)
            if budget is not None and self.tools
            else None
        )

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
            return observe_round(request, patterns)

        def observe_round(request: ObservationRequest, patterns: list[str]) -> str:
            """One round of reading: ask the host, merge, log. See `read_again`
            for the failure rules; the first read before iteration one takes
            the same round, so it cannot bypass them."""
            base = state.evidence_base
            assert base is not None and budget is not None  # guarded at the call
            # Started before the host is asked, for the same reason a model
            # call is: an interruption during the read must not read as a call
            # that never began. Without this, the one path where bytes change
            # under a run was the one path the log could not speak about.
            read = (
                log.start_call(
                    "observe",
                    iteration=state.iteration,
                    target=",".join(request.paths) or None,
                    # The whole request. On a first read `paths` is empty and
                    # the patterns and the question are what was asked for.
                    call_input=request,
                    idempotent=True,
                )
                if log is not None
                else None
            )

            def finish_read(outcome: str, error: str | None = None) -> None:
                if log is not None and read is not None:
                    log.finish_call(
                        read, outcome, iteration=state.iteration, error=error
                    )

            try:
                budget.check()
                incoming = observer.observe(request, budget=budget)  # type: ignore[union-attr]
                merged, round_result = merge_observations(
                    base.snapshot, base.observations, list(incoming)
                )
            except RunCancelled:
                # A cancellation is a control stop, and the read was not
                # refused by anything — it was interrupted. `failed` says the
                # attempt did not produce material, which is what happened.
                finish_read("failed", "RunCancelled")
                state.stop("cancelled")
                return "stopped"
            except BudgetExceeded as exc:
                finish_read("denied", type(exc).__name__)
                state.metadata["budget_exhausted"] = str(exc)
                state.stop("budget_exhausted")
                return "stopped"
            except Exception as exc:
                finish_read("failed", type(exc).__name__)
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
            fresh: list[Observation] = list(round_result.added) + [
                observation
                for observation in merged
                if observation.source_id
                in {item.source_id for item in round_result.superseded}
            ]

            # A resumed run replays from the start and reads again. The bytes
            # the interrupted run recorded for this round are what it graded;
            # a replay that reads different ones is not the same run, so it
            # stops `blocked` — the ground moved — before anything is adopted.
            committed = len(state.metadata.get("observation_rounds", []))
            if committed < len(recorded_rounds):
                expected = recorded_rounds[committed]
                got = _round_material(round_result)
                if got != expected:
                    finish_read("ok")
                    state.metadata["resume_evidence_changed"] = {
                        "round": committed,
                        "source_ids": sorted(
                            {sid for sid, _ in expected ^ got}
                        ),
                    }
                    state.stop("blocked")
                    return "stopped"

            # Charged before anything is adopted. A round the budget cannot
            # pay for is not accepted: no evidence, no log entry, no context.
            contexts = [
                f"{observation.path}:\n{observation.excerpt}" for observation in fresh
            ]
            try:
                for context in contexts:
                    budget.charge_output(context)
            except RunCancelled:
                finish_read("failed", "RunCancelled")
                state.stop("cancelled")
                return "stopped"
            except BudgetExceeded as exc:
                finish_read("denied", type(exc).__name__)
                state.metadata["budget_exhausted"] = str(exc)
                state.stop("budget_exhausted")
                return "stopped"
            finish_read("ok")

            record = round_result.to_dict()
            record["iteration"] = state.iteration
            # What the host was asked to resolve. A pattern it came back from
            # is answered even when it found nothing: that is the run learning
            # the repository has no such file, which it cannot learn any other
            # way without listing directories itself.
            record["patterns"] = list(patterns)
            state.metadata.setdefault("observation_rounds", []).append(record)
            if log is not None:
                # Appended, never replacing an earlier one for the same source.
                # A source that changed under a run is something the log shows:
                # `superseded` carries both digests, so a reader can tell which
                # bytes a claim was graded against rather than only that the
                # source moved.
                log.append(
                    "observation_recorded",
                    iteration=state.iteration,
                    patterns=list(patterns),
                    requested=round_result.requested,
                    # The path too, so `inspect` can say where a source is and
                    # not only its id. Masked with the rest of the payload.
                    added=[
                        {
                            "source_id": item.source_id,
                            "path": item.path,
                            "sha256": item.content_sha256,
                        }
                        for item in round_result.added
                    ],
                    superseded=[
                        {
                            "source_id": item.source_id,
                            "path": item.path,
                            "previous_sha256": item.previous_sha256,
                            "new_sha256": item.new_sha256,
                        }
                        for item in round_result.superseded
                    ],
                    unchanged=list(round_result.unchanged),
                    has_new_material=round_result.has_new_material,
                )
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
            # The prose channel is how a producer learns what is now available;
            # the evidence base is what gets checked. Both are needed, and they
            # stay separate: this text is context, and nothing turns it back
            # into an observation.
            state.observations.extend(contexts)
            return "new"

        #: One material signature per graded pass, in order. See
        #: `_material_signature` for what counts as material and why.
        materials: list[tuple[Any, ...]] = []

        def stopped() -> str | dict[str, Any]:
            """Every exit records its stop. A history without `run_stopped`
            reads as a crash, so an early stop must not skip it."""
            if log is not None:
                log.append(
                    "run_stopped",
                    iteration=state.iteration,
                    stop_reason=state.stop_reason,
                    stop_class=stop_class_of(state.stop_reason),
                    status=state.status,
                    # What the run spent, for telemetry. Null on an unbudgeted
                    # run, which counts nothing.
                    usage=(
                        {key: value for key, value in budget.usage().items()
                         if key != "deadline_monotonic"}
                        if budget is not None else None
                    ),
                )
            return finalize(state, json_mode=json_mode)

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
                return stopped()
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
            return stopped()
        if (
            read_first
            and observer is not None
            and state.evidence_base is not None
            and state.evidence_base.is_empty()
        ):
            # The first read, when the host asks for it. Without `read_first` a
            # run starts from what it was handed and reads when an evaluation
            # names a gap (P1.1). With it, the observer is asked before
            # iteration one, so the first answer is graded against sources.
            # It asks what the plan will ask: the plan is derived from the task
            # and the snapshot, so it is known before the loop builds it.
            first_plan = build_plan(
                task, select_route(task), state.evidence_base.snapshot.snapshot_id
            )
            first_patterns = list(first_plan.review.patterns) if first_plan.review else []
            first_request = request_from(
                state.evidence_base.snapshot, [], [], [], 0,
                patterns=first_patterns,
                question=first_plan.review.question if first_plan.review else "",
            )
            if observe_round(first_request, first_patterns) == "stopped":
                assert budget is not None  # an observer requires RunLimits
                state.metadata["budget_usage"] = budget.usage()
                return stopped()
        while state.iteration < state.max_iterations:
            if expired():
                break
            state.iteration += 1
            state.enter("routing")
            route = select_route(task)
            state.route = route
            if gateway is not None:
                gateway.set_route(route.name)
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
            if log is not None:
                log.append(
                    "plan_selected",
                    iteration=state.iteration,
                    route=route.name,
                    steps=list(plan.steps),
                    question=plan.review.question if plan.review else None,
                )
            state.enter("executing")
            if expired():
                break
            # The previous evaluation is what makes a retry a replan rather than
            # a rerun: it tells the executor which gaps to close this time.
            feedback = state.evaluations[-1] if state.evaluations else None
            if self.model_adapter:
                # Bound before the try: the handlers below read it, and a
                # failure raised before the call was started must not become a
                # NameError that hides the failure it was reporting.
                call: str | None = None
                try:
                    kwargs: dict[str, Any] = dict(
                        task=task, route=route, plan=plan,
                        observations=state.observations, feedback=feedback,
                    )
                    # What the model is handed, before the budget and the tools
                    # join it: those are handles to this run, not input. Hashing
                    # the task alone gave a retry the digest of the first try.
                    model_input = dict(kwargs)
                    if budget is not None:
                        budget.reserve_model()
                        kwargs["budget"] = budget
                    if gateway is not None:
                        kwargs["tools"] = gateway
                    # Started before the call, finished after it. A crash in
                    # between leaves a `call_started` with no outcome, which is
                    # exactly the state a single record could not express: the
                    # provider may already have done everything it was going to
                    # do, so `failed` would invite a retry that repeats it.
                    call = (
                        log.start_call(
                            "model_call",
                            iteration=state.iteration,
                            target=getattr(self.model_adapter, "provider", None)
                            or type(self.model_adapter).__name__,
                            call_input=model_input,
                            idempotent=bool(
                                getattr(self.model_adapter, "idempotent", False)
                            ),
                        )
                        if log is not None
                        else None
                    )
                    model_result = self.model_adapter.execute(**kwargs)
                    _check_model_result(model_result)
                    if log is not None and call is not None:
                        # The provider call ended here, successfully. What
                        # follows — charging tokens, charging output — is
                        # accounting *about* the call, not part of it, and it
                        # can fail on a reply the provider delivered perfectly
                        # well.
                        #
                        # So the handle is cleared. A budget failure below must
                        # not try to finish a call that is already finished: the
                        # log refuses a second outcome, correctly, and that
                        # refusal would replace the budget error it was
                        # reporting and escape `run()` entirely. Enabling the
                        # log would then change what a run does, which is the
                        # one thing a log must never do.
                        log.finish_call(call, "ok", iteration=state.iteration)
                        call = None
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
                    if log is not None and call is not None:
                        log.finish_call(
                            call, "failed", iteration=state.iteration,
                            error=type(exc).__name__,
                        )
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
                # Lifted to the top level because it is a property of the whole
                # run, not of one call: a reader deciding whether this document
                # can be reproduced should not have to know which adapter was
                # used. The adapter is what knows — a stub is deterministic and
                # says nothing, a live provider says this.
                if model_result.metadata.get("determinism") == "non_deterministic":
                    state.metadata["non_deterministic"] = {
                        "reason": "live_model_provider"
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
            if log is not None:
                log.append(
                    "decision_recorded",
                    iteration=state.iteration,
                    passed=evaluation.passed,
                    unmet_criteria=list(evaluation.unmet_criteria),
                    evidence_gaps=list(evaluation.evidence_gaps),
                    next_action=(
                        evaluation.next_action.kind
                        if evaluation.next_action is not None
                        else None
                    ),
                    requires_user_approval=evaluation.requires_user_approval,
                    # Counts only, per verdict: how many of the producer's
                    # claims held, never the claims themselves.
                    citation_verdicts=dict(sorted(Counter(
                        str(check.get("verdict")) for check in evaluation.citation_checks
                    ).items())),
                )
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
        return stopped()
