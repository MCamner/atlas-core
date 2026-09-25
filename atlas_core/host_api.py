"""v1.4 box one: what a separate host process needs to drive a run.

Atlas One — or any host — runs Core as a child process and cannot hold a
Python object across that boundary. It needs five things: a run id before the
run exists (`create`), the run itself, what the run is doing now (`status`), a
way to stop it (`cancel`) and a stream of what it did (`events`).

## One source of truth

Every answer here is read from the durable `JsonlSink` log, plus two sidecar
files next to it that are named by the run id's digest:

| file | written by | means |
| --- | --- | --- |
| `<log>.<digest>.lock` | the run, via `RunLock` | a process is running this id now |
| `<log>.<digest>.cancel` | `request_cancel` | a host asked this run to stop |
| `<log>.writer.lock` | the run, via `RunLock` | a process is writing this log now |

## One writer per log

Concurrent runs appending to one JSONL is refused, not supported: a fresh or
resumed durable run holds the log's writer lock and a second writer gets
`EventLogInUse`. The CLI goes further and runs **one run per event log** — a
host stores `(run_id, event_log)` and every command for that run uses that
file. Serialized runs sharing a log remain possible through the Python API.

## A lost worker is sealed in the log

The public CLI runs the loop in a worker it kills at the deadline. A killed
worker cannot write `run_stopped`, so the parent does, under both locks and
after dropping any torn tail the kill left: the CLI result and the log then
name the same terminal state.

A stop the worker already logged wins, because the log is the audit source.
But then the run finished and only its result was lost: the parent has the
terminal event, not the answer or the evaluations, and must not rebuild an
`atlas-run.v1` from it. The CLI reports a transport failure instead and the
host reads the run through `status` and `inspect`.

Nothing here writes to the event log. A second writer to that file would be a
cross-process locking problem `JsonlSink` explicitly does not solve, and a
cancel request is not something the run *did*: the run records `run_stopped`
with `cancelled` when it honours it, and that is the fact the log keeps.

## What `running` means

A run holds its lock from before `run_started` until after `run_stopped`, so a
held lock is the only evidence that a process is alive. A history with no stop
and no held lock is `interrupted`: the process is gone and nothing will finish
it except `resume`. The order of checks — lock first, log second — is what
keeps a run that stops between the two reads from being called interrupted.

## Cancellation is cooperative

The run checks the request at the same boundaries it checks its budget. A
blocked synchronous call is not preempted by it; the public CLI's worker
deadline remains the hard bound. A request is a one-way, permanent marker for
that run id: it is not withdrawn, because a withdrawn cancel races the run that
may already have read it.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Iterator

from .eventlog import SCHEMA as EVENT_SCHEMA
from .eventlog import EventLog, JsonlSink, ResumeRefused, RunLock, digest, read_jsonl
from .inspect_run import inspect_run
from .machine import STOP_REASONS, stop_class_of

STATUS_SCHEMA = "atlas-status.v1"
STATES: tuple[str, ...] = ("not_found", "running", "finished", "interrupted")

#: Printable, path-safe and bounded. A run id ends up in file names (through
#: its digest), JSONL, process arguments and a UI; none of them should have to
#: escape it.
_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")


class RunIdInUse(ValueError):
    """The id already names a run in this log, or a live process holds it."""


class EventLogInUse(RuntimeError):
    """Another process is writing this event log, or (CLI) it already holds a run."""


class FollowEnded(RuntimeError):
    """`follow_events` stopped without seeing `run_stopped`."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def validate_run_id(run_id: str) -> str:
    if not isinstance(run_id, str) or not _RUN_ID.fullmatch(run_id):
        raise ValueError(
            "run id must be 1-128 characters of A-Z a-z 0-9 . _ : - "
            "and start with a letter or digit"
        )
    return run_id


def new_run_id() -> str:
    return str(uuid.uuid4())


def _sidecar(log_path: str | Path, run_id: str, suffix: str) -> Path:
    return Path(str(log_path) + f".{digest(validate_run_id(run_id))}.{suffix}")


def lock_path(log_path: str | Path, run_id: str) -> Path:
    """The lock a run and a resume hold. Same path `AtlasController.resume` uses."""
    return _sidecar(log_path, run_id, "lock")


def writer_lock_path(log_path: str | Path) -> Path:
    return Path(str(log_path) + ".writer.lock")


def hold(path: Path, *, wait: float = 0.0) -> RunLock:
    """Take a lock or raise `ResumeRefused`; retry up to `wait` seconds."""
    deadline = time.monotonic() + wait
    while True:
        try:
            return RunLock(path).acquire()
        except ResumeRefused:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.05)


def log_holds_a_run(log_path: str | Path) -> bool:
    path = Path(log_path)
    return path.exists() and bool(read_jsonl(path))


def cancel_path(log_path: str | Path, run_id: str) -> Path:
    return _sidecar(log_path, run_id, "cancel")


def is_locked(log_path: str | Path, run_id: str) -> bool:
    """Whether a process holds the run's lock. Never creates the lock file."""
    path = lock_path(log_path, run_id)
    try:
        handle = path.open("r", encoding="utf-8")
    except FileNotFoundError:
        return False
    with handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        return False


def _records(log_path: str | Path, run_id: str) -> list[dict[str, Any]]:
    path = Path(log_path)
    if not path.exists():
        return []
    return [record for record in read_jsonl(path) if record.get("run_id") == run_id]


def run_status(log_path: str | Path, run_id: str) -> dict[str, Any]:
    """An `atlas-status.v1` document. Raises `InspectError` on a history that
    contradicts itself, exactly as `inspect` does — status is not allowed to be
    more forgiving than the report it summarizes."""
    validate_run_id(run_id)
    running = is_locked(log_path, run_id)
    records = _records(log_path, run_id)
    report = inspect_run(log_path, run_id) if records else None
    if report is None:
        state = "running" if running else "not_found"
    elif report["finished_at"] is not None:
        state = "finished"
    else:
        state = "running" if running else "interrupted"
    return {
        "schema": STATUS_SCHEMA,
        "run_id": run_id,
        "state": state,
        "status": report["status"] if report and state == "finished" else None,
        "stop_reason": report["stop_reason"] if report else None,
        "iteration": report["iterations"] if report else 0,
        "event_count": report["event_count"] if report else 0,
        "last_event_kind": records[-1]["kind"] if records else None,
        "cancel_requested": cancel_path(log_path, run_id).exists(),
    }


def request_cancel(log_path: str | Path, run_id: str) -> Path:
    """Ask the run to stop. Idempotent; the marker is permanent for this id."""
    path = cancel_path(log_path, run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT, 0o644)
    os.close(fd)
    return path


def cancel_requested(log_path: str | Path, run_id: str) -> Callable[[], bool]:
    """The `cancelled` hook to hand `AtlasController.run`."""
    path = cancel_path(log_path, run_id)
    return path.exists


def seal_lost_run(
    log_path: str | Path, run_id: str, *, stop_reason: str, detail: str,
    task: str, max_iterations: int,
) -> tuple[str, bool]:
    """Record the stop of a run whose worker is gone.

    Returns the logged stop reason and whether this call wrote it. A stop that
    is already logged is the worker's: the run ended, only its result was lost.

    Waits briefly for the dead worker's locks to be released; raises
    `ResumeRefused` if they are not, or if the history is not a valid log.
    """
    if stop_reason not in STOP_REASONS:
        raise ValueError(f"unknown stop reason {stop_reason!r}")
    writer = hold(writer_lock_path(log_path), wait=2.0)
    run_lock: RunLock | None = None
    try:
        run_lock = hold(lock_path(log_path, run_id), wait=2.0)
        sink = JsonlSink(log_path, truncate_torn_tail=True)
        present = read_jsonl(log_path) if Path(log_path).exists() else []
        if any(r.get("run_id") != run_id for r in present):
            # The CLI runs one run per log. A worker refused for that
            # reason wrote nothing, and sealing would put a second run in.
            raise EventLogInUse(f"{log_path} holds another run; not sealing")
        records = _records(log_path, run_id)
        for record in records:
            if record.get("kind") == "run_stopped":
                return str(record["payload"]["stop_reason"]), False
        log = EventLog(run_id, sink, previous=records)
        if not records:
            # What the parent knows. The hard CLI passes no prose
            # observations; with --repo-path the worker's snapshot was taken
            # in the worker, so the parent records none rather than a guess.
            log.append(
                "run_started",
                task_sha256=digest(task),
                max_iterations=max_iterations,
                observations_sha256=digest([]),
                snapshot_id=None,
                evidence_sha256=None,
                recorded_by="cli_parent",
            )
        log.append(
            "run_stopped",
            iteration=max((int(r.get("iteration", 0)) for r in records), default=0),
            stop_reason=stop_reason,
            stop_class=stop_class_of(stop_reason),
            status=STOP_REASONS[stop_reason].status,
            recorded_by="cli_parent",
            detail=detail,
        )
        return stop_reason, True
    finally:
        if run_lock is not None:
            run_lock.release()
        writer.release()


def follow_events(
    log_path: str | Path, run_id: str, *, timeout: float, poll: float = 0.1,
) -> Iterator[dict[str, Any]]:
    """Yield one run's events as they are appended, ending at `run_stopped`.

    Raises `FollowEnded("interrupted")` when the history has no stop and no
    process holds the lock, and `FollowEnded("timed out")` at the deadline.
    A run that has not written anything yet is waited for, because a host
    usually starts following right after spawning it.
    """
    validate_run_id(run_id)
    deadline = time.monotonic() + timeout
    seen = 0
    while True:
        # Lock before log: a run that stops between the two reads is then seen
        # as stopped, never as interrupted.
        alive = is_locked(log_path, run_id)
        records = _records(log_path, run_id)
        for record in records[seen:]:
            if record.get("schema") != EVENT_SCHEMA:
                raise ValueError(f"event log holds a non-{EVENT_SCHEMA} record")
            yield record
            if record.get("kind") == "run_stopped":
                return
        seen = len(records)
        # A history with no lock file at all was written by something that
        # never took the lock (an older Core, a fixture); the lock cannot tell
        # it from a live run, so only the deadline ends it.
        if records and not alive and lock_path(log_path, run_id).exists():
            raise FollowEnded("interrupted")
        if time.monotonic() >= deadline:
            raise FollowEnded("timed out")
        time.sleep(poll)


def dump_jsonl(record: dict[str, Any]) -> str:
    return json.dumps(record, ensure_ascii=False, sort_keys=True)
