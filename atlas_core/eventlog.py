"""An append-only record of what a run did, in the order it did it.

The run document says where a run ended up. It cannot say what happened on the
way, and it cannot say it *while* the run is happening — it is written once, at
the end, by a process that may not reach the end. This is the other half: one
record per thing, written when the thing happens, never rewritten.

**Append-only is the whole point, so it is enforced rather than intended.**
`append` is the only way in; there is no update and no delete. The log assigns
the sequence number, so two events cannot claim the same position and a caller
cannot renumber history. A durable log opens its file in append mode and writes
one JSON object per line, which means a crash truncates the last line rather
than corrupting the file — and a truncated last line is a missing event, which
is a state this module can already express.

**A call is two events, not one.** `call_started` and `call_finished` are
separate records joined by a `call_id`, because the difference between them is
the only way a reader can tell three situations apart:

    no call_started                     -> the call never began
    call_started, no call_finished      -> it began; the outcome is UNKNOWN
    call_started and call_finished      -> it began and the outcome is recorded

That middle state is the one that matters, and the one a single-record design
loses. A crash between issuing a request and receiving the answer leaves a call
that may have had every effect it was going to have. Reading that as "failed"
would invite a retry that repeats a side effect; reading it as "did not happen"
would be worse. `call_states()` returns `unknown` and says so, and the resume
work that has to decide what to do about it can start from a fact rather than a
guess.

**Historical observations are not overwritten.** An `observation_recorded`
event for a source already recorded is a *new* event, appended after the old
one, and both are in the log with their digests. A source that changed under a
run is something the log shows rather than something it hides — which is the
same rule `Observation` enforces by being frozen, applied over time instead of
over one object.

**What is written is masked.** The run document is redacted on the way out
because a source's bytes reach it through several channels; a durable log is
another channel, and one that persists whether or not anyone exports the run.
The same `redact_document` runs over every event payload before it is written.

What this module does **not** do is resume. It records enough for the resume
work to tell the three states above apart, and stops there. Locking, idempotent
replay and `interrupted`/`resumed` events are their own problem.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Protocol

SCHEMA = "atlas-event.v1"

#: What can be recorded. Closed, because a free-text kind is a category nobody
#: can aggregate over and a log exists to be read by something other than the
#: person who wrote it.
EVENT_KINDS: tuple[str, ...] = (
    "run_started",
    "plan_selected",
    "call_started",
    "call_finished",
    "observation_recorded",
    "decision_recorded",
    "run_stopped",
)

#: What a call can be. The same vocabulary as `atlas-action.v1.kind`, because a
#: call is what an action is a record of, and two vocabularies for one thing
#: drift.
CALL_KINDS: tuple[str, ...] = (
    "observe",
    "model_call",
    "tool_call",
    "memory_read",
    "memory_write",
)

#: What a *finished* call can have been. `unknown` is deliberately not here: it
#: is not an outcome anything reports, it is the absence of a report, and
#: `call_states` produces it from a missing `call_finished` rather than from a
#: value anyone wrote.
CALL_OUTCOMES: tuple[str, ...] = ("ok", "denied", "failed")

#: What `call_states` can say about one call. `unknown` is the state this whole
#: module is shaped around.
CALL_STATES: tuple[str, ...] = ("unknown", *CALL_OUTCOMES)


class AppendOnlyViolation(RuntimeError):
    """An attempt to write history rather than extend it."""


def digest(value: object) -> str:
    """A stable digest of an input, so a replay can be compared against what was
    sent without the input itself being kept."""
    if isinstance(value, str):
        material = value
    else:
        material = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Event:
    """One recorded fact. Frozen, for the reason `Observation` is frozen: a
    record that can be edited after the fact is not a record."""

    run_id: str
    sequence: int
    kind: str
    recorded_at: str
    iteration: int = 0
    #: Joins `call_started` to `call_finished`. Required on both and on nothing
    #: else, so an unpaired call is visible rather than merely likely.
    call_id: str | None = None
    #: Everything specific to the kind. A dict rather than one flat record with
    #: mostly-null columns, because a field that is null for six of seven kinds
    #: teaches a reader nothing.
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in EVENT_KINDS:
            raise ValueError(f"kind must be one of {EVENT_KINDS}, got {self.kind!r}")
        if not self.run_id:
            raise ValueError("an event belongs to a run")
        if self.sequence < 0:
            raise ValueError("sequence is assigned by the log and starts at 0")
        if self.iteration < 0:
            raise ValueError("iteration cannot be negative")
        needs_call = self.kind in ("call_started", "call_finished")
        if needs_call and not self.call_id:
            raise ValueError(
                f"{self.kind} carries a call_id; without one a started call "
                "cannot be matched to its outcome, which is the one distinction "
                "this log exists to keep"
            )
        if not needs_call and self.call_id is not None:
            raise ValueError(f"{self.kind} does not name a call")
        if self.kind == "call_started":
            if self.payload.get("call_kind") not in CALL_KINDS:
                raise ValueError(f"call_started declares a call_kind from {CALL_KINDS}")
        if self.kind == "call_finished":
            if self.payload.get("outcome") not in CALL_OUTCOMES:
                raise ValueError(
                    f"call_finished declares an outcome from {CALL_OUTCOMES}; "
                    "'unknown' is not an outcome anything reports, it is what a "
                    "missing call_finished means"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "event_id": f"{self.run_id}:{self.sequence}",
            "run_id": self.run_id,
            "sequence": self.sequence,
            "iteration": self.iteration,
            "kind": self.kind,
            "recorded_at": self.recorded_at,
            "call_id": self.call_id,
            "payload": dict(self.payload),
        }


class EventSink(Protocol):
    """Where a log's events go. One method, and it only ever adds."""

    def write(self, record: Mapping[str, Any]) -> None:
        ...


class EventLog:
    """The append-only log itself.

    Holds the sequence counter, so nothing outside can assign a position. A
    caller that could choose its own sequence could write an event *before* one
    already recorded, which is the one thing an append-only log promises cannot
    happen.
    """

    def __init__(self, run_id: str, sink: EventSink | None = None) -> None:
        if not run_id:
            raise ValueError("a log belongs to a run")
        self.run_id = run_id
        self._sink = sink
        self._events: list[Event] = []

    def __len__(self) -> int:
        return len(self._events)

    def __iter__(self) -> Iterator[Event]:
        return iter(tuple(self._events))

    def events(self) -> tuple[Event, ...]:
        """A snapshot of what has been recorded. A tuple, so a caller holding it
        cannot append through it."""
        return tuple(self._events)

    def append(
        self,
        kind: str,
        *,
        iteration: int = 0,
        call_id: str | None = None,
        **payload: Any,
    ) -> Event:
        """Record one fact and return it. The only way in.

        The payload is masked before it is written, because this file persists
        whether or not anyone exports the run, and a source's bytes reach it the
        same way they reach the run document.
        """
        from .redaction import redact_document

        event = Event(
            run_id=self.run_id,
            sequence=len(self._events),
            kind=kind,
            recorded_at=datetime.now(timezone.utc).isoformat(),
            iteration=iteration,
            call_id=call_id,
            payload=redact_document(dict(payload)),
        )
        self._events.append(event)
        if self._sink is not None:
            self._sink.write(event.to_dict())
        return event

    def start_call(
        self, call_kind: str, *, iteration: int = 0, target: str | None = None,
        call_input: object = None, **payload: Any,
    ) -> str:
        """Record that a call began, and return the id its outcome must carry.

        The id is issued here rather than taken from the caller, so a call
        cannot be finished that was never started under that name.
        """
        call_id = f"{self.run_id}:{len(self._events)}"
        self.append(
            "call_started",
            iteration=iteration,
            call_id=call_id,
            call_kind=call_kind,
            target=target,
            # The digest, never the input. A replay can be compared against it
            # without the input being kept anywhere.
            input_sha256=digest(call_input) if call_input is not None else None,
            **payload,
        )
        return call_id

    def finish_call(
        self, call_id: str, outcome: str, *, iteration: int = 0,
        error: str | None = None, **payload: Any,
    ) -> Event:
        if not any(
            event.kind == "call_started" and event.call_id == call_id
            for event in self._events
        ):
            raise AppendOnlyViolation(
                f"no call_started for {call_id!r}; an outcome for a call that "
                "never began would be a record of something that did not happen"
            )
        if any(
            event.kind == "call_finished" and event.call_id == call_id
            for event in self._events
        ):
            raise AppendOnlyViolation(
                f"{call_id!r} already finished; a second outcome would overwrite "
                "the first, and this log does not overwrite"
            )
        return self.append(
            "call_finished",
            iteration=iteration,
            call_id=call_id,
            outcome=outcome,
            error=error,
            **payload,
        )


class JsonlSink:
    """One JSON object per line, opened in append mode and flushed per write.

    A crash truncates the last line rather than corrupting the file, and a
    truncated last line is a missing event — a state `call_states` already
    expresses. Buffering would trade exactly the events a crash makes
    interesting for a little throughput.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, record: Mapping[str, Any]) -> None:
        line = json.dumps(record, ensure_ascii=False, sort_keys=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()
            os.fsync(handle.fileno())


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    """Every whole record in a log file, in order.

    A trailing partial line is dropped rather than raising: it is what a crash
    during a write leaves behind, and the events before it are still true. A
    malformed line anywhere else is a different matter and raises, because that
    is corruption rather than interruption.
    """
    records: list[dict[str, Any]] = []
    lines = Path(path).read_text(encoding="utf-8").splitlines(keepends=True)
    for index, line in enumerate(lines):
        last = index == len(lines) - 1
        if not line.endswith("\n") and last:
            # Torn write. The record was never completed, so it never happened.
            break
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            if last:
                break
            raise
    return records


def call_states(events: Iterable[Event | Mapping[str, Any]]) -> dict[str, str]:
    """What the log can attest about each call it names.

    `unknown` for a call that began and has no recorded outcome. Not `failed`,
    which would invite a retry that repeats a side effect the first attempt may
    already have had, and not absence, which would say it never began. A call
    that was never started is simply not in the result.
    """
    started: dict[str, str] = {}
    for event in events:
        record = event.to_dict() if isinstance(event, Event) else dict(event)
        call_id = record.get("call_id")
        if not isinstance(call_id, str):
            continue
        if record.get("kind") == "call_started":
            started.setdefault(call_id, "unknown")
        elif record.get("kind") == "call_finished" and call_id in started:
            outcome = record.get("payload", {}).get("outcome")
            if outcome in CALL_OUTCOMES:
                started[call_id] = str(outcome)
    return started


def unfinished_calls(events: Iterable[Event | Mapping[str, Any]]) -> list[str]:
    """The calls whose outcome nobody recorded. What resume has to reason about,
    and the reason a call is two events."""
    return [call for call, state in call_states(events).items() if state == "unknown"]


__all__ = [
    "AppendOnlyViolation",
    "CALL_KINDS",
    "CALL_OUTCOMES",
    "CALL_STATES",
    "EVENT_KINDS",
    "Event",
    "EventLog",
    "EventSink",
    "JsonlSink",
    "SCHEMA",
    "call_states",
    "digest",
    "read_jsonl",
    "unfinished_calls",
]
