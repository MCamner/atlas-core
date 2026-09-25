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

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Iterator, Mapping

from .eventlog import read_jsonl
from .redaction import redact_text

CANDIDATE_SCHEMA = "atlas-learning-candidate.v1"
LEARNING_SCHEMA = "atlas-learning.v1"
OUTCOMES: tuple[str, ...] = ("confirmed", "rejected")
MAX_LESSON = 2000


#: `schemas/atlas-learning-candidate.v1.json`, carried here because the schema
#: files are not installed with the package. A test holds the two equal.
CANDIDATE_JSON_SCHEMA: dict[str, Any] = json.loads(r"""
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "atlas-learning-candidate.v1.json",
  "title": "Atlas Learning Candidate",
  "description": "A person's verdict on a finished run and what they think should be learned from it. A candidate is not knowledge: nothing reads it as such until `atlas feedback promote` passes it through the schema and provenance gate and a named person promotes it.",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "schema",
    "candidate_id",
    "run_id",
    "outcome",
    "lesson",
    "provenance",
    "recorded_by",
    "recorded_at"
  ],
  "properties": {
    "schema": {
      "const": "atlas-learning-candidate.v1"
    },
    "candidate_id": {
      "type": "string",
      "pattern": "^[0-9a-f]{32}$",
      "description": "Derived from run, outcome, lesson and provenance."
    },
    "run_id": {
      "type": "string",
      "minLength": 1
    },
    "outcome": {
      "enum": [
        "confirmed",
        "rejected"
      ]
    },
    "lesson": {
      "type": "string",
      "minLength": 1,
      "maxLength": 2000,
      "description": "The person's words, masked like every other text Core keeps."
    },
    "provenance": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "event_log_sha256",
        "run_stopped_event_id",
        "stop_reason",
        "task_sha256",
        "route",
        "sources"
      ],
      "description": "Read from the run's event log when the outcome was recorded. The gate compares every field with the log again before promotion.",
      "properties": {
        "event_log_sha256": {
          "type": "string",
          "pattern": "^[0-9a-f]{64}$",
          "description": "The whole log file. A run's log is closed at `run_stopped`, so a different digest means the evidence changed."
        },
        "run_stopped_event_id": {
          "type": "string"
        },
        "stop_reason": {
          "type": [
            "string",
            "null"
          ]
        },
        "task_sha256": {
          "type": [
            "string",
            "null"
          ]
        },
        "route": {
          "type": [
            "string",
            "null"
          ]
        },
        "sources": {
          "type": "array",
          "items": {
            "type": "object",
            "additionalProperties": false,
            "required": [
              "source_id",
              "path",
              "sha256"
            ],
            "properties": {
              "source_id": {
                "type": "string"
              },
              "path": {
                "type": "string"
              },
              "sha256": {
                "type": "string"
              }
            }
          }
        }
      }
    },
    "recorded_by": {
      "type": "string",
      "minLength": 1
    },
    "recorded_at": {
      "type": "string"
    }
  }
}
""")

_TYPES: dict[str, Any] = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "null": lambda v: v is None,
}


def schema_errors(value: Any, schema: Mapping[str, Any], path: str = "$") -> list[str]:
    """Every way `value` departs from `schema`, for the keywords the candidate
    schema uses. A keyword this does not know is an error, not a pass."""
    known = {"$schema", "$id", "title", "description", "type", "const", "enum",
             "pattern", "minLength", "maxLength", "required", "properties",
             "additionalProperties", "items"}
    unknown = set(schema) - known
    if unknown:
        return [f"{path}: schema uses unsupported keywords {sorted(unknown)}"]
    errors: list[str] = []
    if "type" in schema:
        allowed = [schema["type"]] if isinstance(schema["type"], str) else schema["type"]
        if not any(_TYPES[name](value) for name in allowed):
            return [f"{path}: not {allowed}"]
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: not {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: not one of {schema['enum']}")
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{path}: shorter than {schema['minLength']}")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(f"{path}: longer than {schema['maxLength']}")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(f"{path}: does not match {schema['pattern']}")
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}.{key}: missing")
        if schema.get("additionalProperties") is False:
            errors.extend(f"{path}.{key}: not allowed" for key in sorted(set(value) - set(properties)))
        for key, item in value.items():
            if key in properties:
                errors.extend(schema_errors(item, properties[key], f"{path}.{key}"))
    if isinstance(value, list) and "items" in schema:
        for index, item in enumerate(value):
            errors.extend(schema_errors(item, schema["items"], f"{path}[{index}]"))
    return errors


def _candidate_id(body: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:32]


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
        "candidate_id": _candidate_id(body),
        **body,
        "recorded_by": recorded_by,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    _append(Path(store) / "candidates.jsonl", candidate)
    return candidate


def gate(candidate: Mapping[str, Any], event_log: str | Path) -> list[str]:
    """Why `candidate` may not be promoted; empty when it may."""
    # 1. The whole document against the published schema.
    problems = schema_errors(dict(candidate), CANDIDATE_JSON_SCHEMA)
    if problems:
        return problems
    for key in ("run_id", "lesson", "recorded_by"):
        if not str(candidate[key]).strip():
            problems.append(f"$.{key}: blank")
    # 2. The id is derived from the content, so content edited under an old
    #    id is a different candidate wearing its name.
    body = {key: candidate[key] for key in ("run_id", "outcome", "lesson", "provenance")}
    if _candidate_id(body) != candidate["candidate_id"]:
        problems.append("candidate_id does not match its content")
    if problems:
        return problems
    provenance = candidate["provenance"]
    # 3. The provenance against the log as it is now.
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
    # Check-then-append is one step: two promotions of one candidate must not
    # both find it unpromoted. The second waits, then sees the first's line.
    with _store_lock(root):
        return _promote(root, candidate_id, event_log, promoted_by)


@contextmanager
def _store_lock(root: Path) -> Iterator[None]:
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".promote.lock").open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _promote(root: Path, candidate_id: str, event_log: str | Path,
             promoted_by: str) -> dict[str, Any]:
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
    "CANDIDATE_JSON_SCHEMA",
    "gate",
    "schema_errors",
    "promote",
    "record_outcome",
]
