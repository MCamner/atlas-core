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
from .eventlog import digest, read_jsonl
from .inspect_run import inspect_run

STATUS_SCHEMA = "atlas-status.v1"
STATES: tuple[str, ...] = ("not_found", "running", "finished", "interrupted")

#: Printable, path-safe and bounded. A run id ends up in file names (through
#: its digest), JSONL, process arguments and a UI; none of them should have to
#: escape it.
_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")


class RunIdInUse(ValueError):
    """The id already names a run in this log, or a live process holds it."""


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
