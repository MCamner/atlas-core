"""The run's state machine: which states exist, and how a run may end.

A run has always had a `status` and a `stop_reason`, but nothing held them
together. They were written at five separate points in the controller, and a
pair that disagreed — `done` beside a runtime failure, say — was a plain
assignment away. This module makes the pair a single fact: a reason names its
own terminal status and its own exit code, and stopping a run means naming the
reason, never setting the two fields by hand.

The distinction the reasons exist to carry is the one ROADMAP.md P0.3 asks for:
**a runtime error is not a judgement about an answer.** So every reason
declares a `StopClass`:

- `evaluation` — an answer was produced and graded, and this is the grade.
- `runtime` — the machinery failed, so the *ending* is not a verdict. An
  earlier iteration may have left an evaluation behind; it was not promoted,
  and a caller that reads the run's outcome off it is reading a grade the run
  never claimed.
- `control` — a bound, a human or a cancellation ended the run. Whatever grade
  exists is provisional: the loop stopped before it was finished, not because
  it was.

`insufficient_evidence` and `no_progress` are both honest failures, and they
are not the same failure. The first says the claims were not established
against what was read. The second says nothing about the claims at all: it
says another identical pass would produce the identical output, so the loop
declined to spend an iteration proving that. Telling them apart is the whole
point of naming a reason rather than returning a boolean.

The vocabulary is versioned. `schemas/atlas-state-machine.v1.json` is the same
table as data, for a consumer that has to branch on it without importing
Python, and a test holds the two in step.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal

#: Bumped when a status or a stop reason changes meaning, is removed, or is
#: retyped. Adding a reason is additive and keeps the version, in the same way
#: a new optional field keeps a schema version.
STATE_MACHINE_VERSION = "atlas-state-machine.v1"

Status = Literal[
    "new",
    "observing",
    "routing",
    "planning",
    "executing",
    "evaluating",
    "replanning",
    "need_user_approval",
    "done",
    "failed",
    "cancelled",
]

StopReason = Literal[
    "passed",
    "insufficient_evidence",
    "blocked",
    "approval_required",
    "budget_exhausted",
    "max_iterations",
    "no_progress",
    "tool_error",
    "cancelled",
]

#: Statuses from which nothing further happens. A run in one of these is over.
TERMINAL_STATUSES: frozenset[str] = frozenset(
    {"need_user_approval", "done", "failed", "cancelled"}
)


class StopClass(str, Enum):
    """What kind of thing ended the run. See the module docstring."""

    EVALUATION = "evaluation"
    RUNTIME = "runtime"
    CONTROL = "control"


@dataclass(frozen=True)
class StopSpec:
    """One stop reason, with everything that must agree with it."""

    reason: StopReason
    stop_class: StopClass
    #: The terminal status a run carries when it stops for this reason. Held
    #: here rather than chosen at the call site, so the two cannot drift.
    status: Status
    #: What `atlas run` returns. A published exit code is a contract; a caller
    #: branches on it without parsing prose.
    exit_code: int
    meaning: str

    @property
    def is_runtime(self) -> bool:
        return self.stop_class is StopClass.RUNTIME


def _spec(
    reason: StopReason,
    stop_class: StopClass,
    status: Status,
    exit_code: int,
    meaning: str,
) -> tuple[str, StopSpec]:
    return reason, StopSpec(reason, stop_class, status, exit_code, meaning)


STOP_REASONS: dict[str, StopSpec] = dict(
    [
        _spec(
            "passed",
            StopClass.EVALUATION,
            "done",
            0,
            "The answer was graded and met its gate.",
        ),
        _spec(
            "insufficient_evidence",
            StopClass.EVALUATION,
            "done",
            2,
            "The answer was graded and its claims were not established against "
            "what the run read. This is a verdict on the answer, not an error.",
        ),
        _spec(
            "blocked",
            StopClass.CONTROL,
            "done",
            2,
            "The run cannot continue without something it cannot obtain by "
            "itself: a source it cited has moved or vanished, so the ground "
            "moved under the run rather than the answer being wrong.",
        ),
        _spec(
            "approval_required",
            StopClass.CONTROL,
            "need_user_approval",
            3,
            "The task appears to require mutation, which a human authorises "
            "before anything runs.",
        ),
        _spec(
            "budget_exhausted",
            StopClass.CONTROL,
            "done",
            2,
            "A declared limit other than the iteration bound was reached.",
        ),
        _spec(
            "max_iterations",
            StopClass.CONTROL,
            "done",
            2,
            "A gap remained that another pass could have acted on, and the "
            "iteration bound stopped the run from trying.",
        ),
        _spec(
            "no_progress",
            StopClass.CONTROL,
            "done",
            2,
            "Nothing was left that another pass could change, so a further "
            "iteration would produce the same output and fail the same way.",
        ),
        _spec(
            "tool_error",
            StopClass.RUNTIME,
            "failed",
            1,
            "The machinery failed, so the run's outcome is not a verdict on "
            "an answer. An evaluation from an earlier iteration may survive in "
            "the record; it was not promoted to the run's result.",
        ),
        _spec(
            "cancelled",
            StopClass.CONTROL,
            "cancelled",
            4,
            "The run was stopped from outside before it reached a verdict.",
        ),
    ]
)

#: What the run document used to say, and what it says now. Kept so a stored
#: `atlas-run.v1` document from before this change can still be read: the
#: schema keeps accepting the old spellings, and nothing emits them.
LEGACY_STOP_REASONS: dict[str, str] = {
    "failed": "tool_error",
    "no_actionable_retry": "insufficient_evidence",
}

#: Where a run may go from where it is. A runtime failure can strike wherever
#: the machinery runs, and so can a cancellation, so both are reachable from
#: every working status. The rest of the loop is a fixed order, and a
#: transition outside it is a bug in the controller rather than a state a run
#: can legitimately reach.
# Control bounds can stop while observing, routing or planning, not only
# after the evaluator. Add done to working-state interruptions; terminal
# states remain immutable. Both Python and the published table must agree.
_INTERRUPTIONS: frozenset[str] = frozenset({"done", "failed", "cancelled"})

_LOOP: dict[str, frozenset[str]] = {
    "new": frozenset({"observing"}),
    "observing": frozenset({"routing"}),
    "routing": frozenset({"planning"}),
    "planning": frozenset({"executing"}),
    "executing": frozenset({"evaluating"}),
    "evaluating": frozenset({"replanning", "done", "need_user_approval"}),
    # `done` as well as `routing`: the loop can decide to go again and then be
    # stopped by its own bound before it does.
    "replanning": frozenset({"routing", "done"}),
    # Terminal. Nothing leaves them, including another terminal status: a run
    # that has failed must not be able to report itself done afterwards.
    "need_user_approval": frozenset(),
    "done": frozenset(),
    "failed": frozenset(),
    "cancelled": frozenset(),
}

TRANSITIONS: dict[str, frozenset[str]] = {
    status: targets if status in TERMINAL_STATUSES else targets | _INTERRUPTIONS
    for status, targets in _LOOP.items()
}


class InvalidTransition(RuntimeError):
    """A run was asked to move somewhere the machine does not allow.

    Raised rather than logged. An illegal transition means the controller lost
    track of where the run is, and a run whose recorded state is wrong reports
    a stop reason that is also wrong — which is the failure this module exists
    to prevent.
    """


def is_legal(source: str, target: str) -> bool:
    return target in TRANSITIONS.get(source, frozenset())


def check_transition(source: str, target: str) -> None:
    if target not in TRANSITIONS:
        raise InvalidTransition(f"{target!r} is not a status in {STATE_MACHINE_VERSION}")
    if not is_legal(source, target):
        allowed = ", ".join(sorted(TRANSITIONS[source])) or "nothing: it is terminal"
        raise InvalidTransition(
            f"a run cannot move from {source!r} to {target!r}; from {source!r} it may "
            f"reach {allowed}"
        )


def spec_for(reason: str) -> StopSpec:
    """The specification for a stop reason, refusing one that is not declared."""
    try:
        return STOP_REASONS[reason]
    except KeyError:
        raise ValueError(
            f"{reason!r} is not a stop reason in {STATE_MACHINE_VERSION}"
        ) from None


def stop_class_of(reason: str | None) -> str | None:
    return None if reason is None else spec_for(reason).stop_class.value


def classify_stop(
    *,
    passed: bool,
    requires_approval: bool,
    blocked_by: list[str],
    evidence_gaps: list[str],
    retry_is_possible: bool,
    iterations_left: bool,
) -> StopReason:
    """Name why a graded run ended, from what the evaluation found.

    Takes plain values rather than an evaluation object, so the decision can be
    read and tested as the table it is. Order is the priority: the first rule
    that matches is the most specific true thing about the run.

    The iteration bound is only the reason when it actually bound something.
    A run with nothing left to try did not stop because it ran out of passes,
    and reporting `max_iterations` there would send a reader to raise a limit
    that was never the constraint.
    """
    if requires_approval:
        return "approval_required"
    if passed:
        return "passed"
    # A source that moved is not a wrong answer. It calls for observing again,
    # which is a different action from correcting a claim, so it outranks the
    # evidence verdict a re-citation could not have changed anyway.
    if blocked_by:
        return "blocked"
    if retry_is_possible and not iterations_left:
        return "max_iterations"
    if evidence_gaps:
        return "insufficient_evidence"
    return "no_progress"


def exit_codes() -> dict[str, int]:
    """The exit code per stop reason, derived rather than kept by hand."""
    return {reason: spec.exit_code for reason, spec in STOP_REASONS.items()}
