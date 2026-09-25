"""Feedback loop: a person's verdict on a run becomes a candidate, never a fact.

Four steps, each separate, and none automatic:

1. `record_outcome` — a person says a finished run's result was `confirmed` or
   `rejected`, and in their own words what should be learned. That becomes an
   `atlas-learning-candidate.v1` appended to `<store>/candidates.jsonl`, with
   provenance read from the run's event log: the log's SHA-256 at that moment,
   the `run_stopped` event, the task digest, the route and every source the run
   read (path and SHA-256).
2. The candidate is only a candidate. Nothing reads `candidates.jsonl` as
   knowledge.
3. `gate` checks a candidate against its schema and against the log it names:
   the log must still hash to what was recorded (a run's log is closed at
   `run_stopped`, so any change is a change to the evidence), and the stop,
   task and sources must be in it as the candidate says.
4. `promote` — an explicit call per candidate, by a named person — reruns the
   gate and appends an `atlas-learning.v1` to `<store>/learnings.jsonl`. A
   candidate is promoted at most once.

Nothing here writes to an event log or rewrites a line of the store: history is
appended to, never edited. The older `build_memory_candidate` marks itself
`verified` from a quality score; that is not this loop, and nothing here
promotes from it.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

from .eventlog import read_jsonl
from .redaction import redact_text

CANDIDATE_SCHEMA = "atlas-learning-candidate.v1"
LEARNING_SCHEMA = "atlas-learning.v1"
OUTCOMES: tuple[str, ...] = ("confirmed", "rejected")
MAX_LESSON = 2000


class PromotionRefused(ValueError):
    def __init__(self, reasons: list[str]) -> None:
        super().__init__("; ".join(reasons))
        self.reasons = reasons


def _sha256_file(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _append(path: Path, record: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = (json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(fd, line)
    finally:
        os.close(fd)


def _read(path: Path) -> list[dict[str, Any]]:
    return read_jsonl(path) if path.exists() else []


def _provenance(event_log: str | Path, run_id: str) -> dict[str, Any]:
    records = [r for r in read_jsonl(event_log) if r.get("run_id") == run_id]
    stopped = [r for r in records if r.get("kind") == "run_stopped"]
    started = [r for r in records if r.get("kind") == "run_started"]
    if not started or not stopped:
        raise ValueError(f"run {run_id!r} has not finished in {event_log}; "
                         "only a finished run has an outcome to judge")
    routes = [r["payload"].get("route") for r in records if r.get("kind") == "plan_selected"]
    sources: dict[str, dict[str, str]] = {}
    for record in records:
        if record.get("kind") == "observation_recorded":
            for added in record.get("payload", {}).get("added", []):
                sources[f"{added.get('source_id')}:{added.get('sha256')}"] = {
                    "source_id": str(added.get("source_id")),
                    "path": str(added.get("path")),
                    "sha256": str(added.get("sha256")),
                }
    return {
        "event_log_sha256": _sha256_file(event_log),
        "run_stopped_event_id": f"{run_id}:{stopped[-1].get('sequence')}",
        "stop_reason": stopped[-1].get("payload", {}).get("stop_reason"),
        "task_sha256": started[0].get("payload", {}).get("task_sha256"),
        "route": routes[-1] if routes else None,
        "sources": sorted(sources.values(), key=lambda s: (s["path"], s["sha256"])),
    }


def record_outcome(
    store: str | Path, event_log: str | Path, run_id: str, *,
    outcome: str, lesson: str, recorded_by: str,
) -> dict[str, Any]:
    """A person's verdict on a finished run, appended as a candidate."""
    if outcome not in OUTCOMES:
        raise ValueError(f"outcome must be one of {OUTCOMES}")
    if not lesson.strip():
        raise ValueError("a candidate says what should be learned")
    if len(lesson) > MAX_LESSON:
        raise ValueError(f"lesson is longer than {MAX_LESSON} characters")
    if not recorded_by.strip():
        raise ValueError("an outcome names who recorded it")
    provenance = _provenance(event_log, run_id)
    body = {
        "run_id": run_id,
        "outcome": outcome,
        # Masked like everything else Core keeps: a pasted credential in a
        # note is still a credential.
        "lesson": redact_text(lesson.strip()),
        "provenance": provenance,
    }
    candidate = {
        "schema": CANDIDATE_SCHEMA,
        "candidate_id": hashlib.sha256(
            json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()[:32],
        **body,
        "recorded_by": recorded_by,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    _append(Path(store) / "candidates.jsonl", candidate)
    return candidate


def gate(candidate: Mapping[str, Any], event_log: str | Path) -> list[str]:
    """Why `candidate` may not be promoted; empty when it may."""
    problems: list[str] = []
    strings = ("candidate_id", "run_id", "outcome", "lesson", "recorded_by", "recorded_at")
    if candidate.get("schema") != CANDIDATE_SCHEMA:
        problems.append("schema")
    for key in strings:
        if not isinstance(candidate.get(key), str) or not candidate[key].strip():
            problems.append(f"{key} missing")
    if candidate.get("outcome") not in OUTCOMES:
        problems.append("outcome not in vocabulary")
    provenance = candidate.get("provenance")
    if not isinstance(provenance, Mapping):
        return problems + ["provenance missing"]
    if problems:
        return problems
    try:
        current = _provenance(event_log, str(candidate["run_id"]))
    except (OSError, ValueError) as exc:
        return [f"event log unreadable: {type(exc).__name__}"]
    if current["event_log_sha256"] != provenance.get("event_log_sha256"):
        problems.append("event log changed since the outcome was recorded")
    for key in ("run_stopped_event_id", "stop_reason", "task_sha256", "route", "sources"):
        if current[key] != provenance.get(key):
            problems.append(f"provenance.{key} does not match the event log")
    return problems


def promote(
    store: str | Path, candidate_id: str, event_log: str | Path, *, promoted_by: str,
) -> dict[str, Any]:
    """Opt in, per candidate: gate it again and append it as a learning."""
    if not promoted_by.strip():
        raise PromotionRefused(["a promotion names who made it"])
    root = Path(store)
    found = [c for c in _read(root / "candidates.jsonl") if c.get("candidate_id") == candidate_id]
    if not found:
        raise PromotionRefused([f"no candidate {candidate_id!r}"])
    if len(found) > 1:
        raise PromotionRefused([f"candidate {candidate_id!r} is recorded more than once"])
    if any(learning.get("candidate", {}).get("candidate_id") == candidate_id
           for learning in _read(root / "learnings.jsonl")):
        raise PromotionRefused([f"candidate {candidate_id!r} is already promoted"])
    problems = gate(found[0], event_log)
    if problems:
        raise PromotionRefused(problems)
    learning = {
        "schema": LEARNING_SCHEMA,
        "candidate": found[0],
        "promoted_by": promoted_by,
        "promoted_at": datetime.now(timezone.utc).isoformat(),
    }
    _append(root / "learnings.jsonl", learning)
    return learning


__all__ = [
    "CANDIDATE_SCHEMA",
    "LEARNING_SCHEMA",
    "OUTCOMES",
    "PromotionRefused",
    "gate",
    "promote",
    "record_outcome",
]
