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

Resume extends this record without pretending it contains source bytes.
`run_started` binds the run to digests of its initial inputs and snapshot id;
the host supplies those inputs again and the controller compares them before
replay. `RunLock` serializes one run id, and `interrupted`/`resumed` make the
continuation explicit. Unknown calls are replayed only when their start event
declared them idempotent.
"""

from __future__ import annotations

import hashlib
import json
import os
import fcntl
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Protocol

SCHEMA = "atlas-event.v1"

#: What can be recorded. Closed, because a free-text kind is a category nobody
#: can aggregate over and a log exists to be read by something other than the
#: person who wrote it.
EVENT_KINDS: tuple[str, ...] = (
    "run_started",
    "interrupted",
    "resumed",
    "plan_selected",
    "call_started",
    "call_finished",
    "observation_recorded",
    "decision_recorded",
    "approval_recorded",
    "write_verified",
    "run_stopped",
)

#: What an `approval_recorded` event can say: a person was asked, answered yes
#: or no, and the yes was spent or refused at the moment of the write.
APPROVAL_DECISIONS: tuple[str, ...] = (
    "requested", "granted", "refused", "consumed", "rejected",
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


class ResumeRefused(RuntimeError):
    """A persisted run cannot be resumed without guessing or duplicating work."""


def _canonical(value: object) -> object:
    # A dataclass by its fields, not by its `repr`: the fields are the input,
    # and a `repr` is a presentation that may change without the input changing.
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    return str(value)


def digest(value: object) -> str:
    """A stable digest of an input, so a replay can be compared against what was
    sent without the input itself being kept.

    Of the **whole** input. A digest over part of it says "same" for calls that
    were handed different things, which is the one answer a replay must never
    get wrong."""
    if isinstance(value, str):
        material = value
    else:
        material = json.dumps(
            value, sort_keys=True, ensure_ascii=False, default=_canonical
        )
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
        if self.kind == "approval_recorded":
            if self.payload.get("decision") not in APPROVAL_DECISIONS:
                raise ValueError(
                    f"approval_recorded declares a decision from {APPROVAL_DECISIONS}"
                )
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

    def __init__(
        self,
        run_id: str,
        sink: EventSink | None = None,
        *,
        previous: Iterable[Mapping[str, Any]] = (),
    ) -> None:
        if not run_id:
            raise ValueError("a log belongs to a run")
        self.run_id = run_id
        self._sink = sink
        self._events = [self._event_from_record(record) for record in previous]
        if any(event.run_id != run_id for event in self._events):
            raise ResumeRefused("a resume log must contain exactly one run id")
        if [event.sequence for event in self._events] != list(range(len(self._events))):
            raise ResumeRefused("event sequence is not contiguous from zero")

    @staticmethod
    def _event_from_record(record: Mapping[str, Any]) -> Event:
        if record.get("schema") != SCHEMA:
            raise ResumeRefused("resume requires atlas-event.v1 records")
        return Event(
            run_id=str(record.get("run_id", "")),
            sequence=int(record.get("sequence", -1)),
            kind=str(record.get("kind", "")),
            recorded_at=str(record.get("recorded_at", "")),
            iteration=int(record.get("iteration", 0)),
            call_id=record.get("call_id"),
            payload=dict(record.get("payload", {})),
        )

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


class TornLogTail(RuntimeError):
    """The file ends mid-record, so appending to it would corrupt it.

    A crash between writing a record and writing its newline leaves bytes with
    no line ending. Reading tolerates that — the record was never completed, so
    it never happened. **Appending does not**, because the next whole object
    would be concatenated onto the fragment and become one invalid line in the
    middle of the file, which is corruption rather than interruption and takes
    the following events down with it.

    So this is raised when the sink is built rather than on the write that would
    do the damage, and the caller decides. `JsonlSink(path,
    truncate_torn_tail=True)` drops the fragment, which is the only operation
    that leaves the file consistent with how reading already treats it.
    """


class JsonlSink:
    """One JSON object per line, opened in append mode and flushed per write.

    A crash truncates the last line rather than corrupting the file, and a
    truncated last line is a missing event — a state `call_states` already
    expresses. Buffering would trade exactly the events a crash makes
    interesting for a little throughput.

    **The tail is checked when the sink is built**, not on every write. A file
    that ends mid-record cannot be safely appended to, and a run that discovers
    that halfway through has already written events into a file it is damaging.
    Failing where the destination is chosen is failing where the decision is.

    Concurrent writers are a different problem and this does not solve it. Two
    processes appending to one file is a locking question, and locking belongs
    to the resume work.
    """

    def __init__(self, path: str | Path, *, truncate_torn_tail: bool = False) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._check_tail(truncate_torn_tail)

    def _check_tail(self, truncate: bool) -> None:
        if not self.path.exists():
            return
        with self.path.open("rb") as handle:
            if handle.seek(0, os.SEEK_END) == 0:
                return
            handle.seek(-1, os.SEEK_END)
            if handle.read(1) == b"\n":
                return
        if not truncate:
            raise TornLogTail(
                f"{self.path} ends mid-record; appending would join the next "
                "event onto the fragment and make that line unreadable. Pass "
                "truncate_torn_tail=True to drop the fragment, which is what "
                "reading already takes it to mean."
            )
        # Only ever the bytes after the last newline: a record that was never
        # completed, which by this module's own reading never happened.
        raw = self.path.read_bytes()
        self.path.write_bytes(raw[: raw.rindex(b"\n") + 1] if b"\n" in raw else b"")

    def write(self, record: Mapping[str, Any]) -> None:
        line = json.dumps(record, ensure_ascii=False, sort_keys=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()
            os.fsync(handle.fileno())


class RunLock:
    """An advisory, process-wide lock held for one run or resume attempt."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._handle: Any = None

    def acquire(self) -> "RunLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            handle.close()
            raise ResumeRefused(f"run is already locked: {self.path}") from exc
        self._handle = handle
        return self

    def release(self) -> None:
        if self._handle is None:
            return
        fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        self._handle.close()
        self._handle = None

    def __enter__(self) -> "RunLock":
        return self.acquire()

    def __exit__(self, *_: object) -> None:
        self.release()


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
        if not line.endswith("\n") and index == len(lines) - 1:
            # Torn write, and the *only* thing tolerated here. The record was
            # never completed, so it never happened.
            break
        if not line.strip():
            continue
        # No exception for the last line. A line that ends with a newline was
        # written in full, so if it does not parse it is corruption — and a
        # reader that shrugged at corruption wherever it happened to sit would
        # be reporting a log that never existed.
        records.append(json.loads(line))
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
    "APPROVAL_DECISIONS",
    "AppendOnlyViolation",
    "CALL_KINDS",
    "CALL_OUTCOMES",
    "CALL_STATES",
    "EVENT_KINDS",
    "Event",
    "EventLog",
    "EventSink",
    "JsonlSink",
    "ResumeRefused",
    "RunLock",
    "TornLogTail",
    "SCHEMA",
    "call_states",
    "digest",
    "read_jsonl",
    "unfinished_calls",
]
