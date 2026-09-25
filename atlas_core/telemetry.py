"""Structured telemetry, read from event logs: `atlas-metrics.v1`.

The event log is already the record of what happened, so metrics are a
reading of it rather than a second channel a run writes to. That keeps one
source: a metric cannot say something the log does not.

What is counted, per run: latency (first to last event), iterations, what the
budget spent (model calls, tool calls, tokens, output bytes), call outcomes by
kind, claims checked and how many held (`verified`) or were refuted by their
own cited source (`contradicted` — the producer's false positives), approvals
asked, granted, refused and rejected, and writes verified or rolled back.

What never is: task text, paths, repositories, refs, user names, error
messages, digests, or any payload string that is not one of the closed
vocabularies below. A run id is shown only in the UUID form `atlas create`
issues; a host-chosen run id is shown as `sha256:` and 16 hex digits of it. The output is built from an allowlist, not by removing
what looks sensitive, so a new payload field cannot leak into it.

Cost is not reported. Core has no price data; tokens are what it knows.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import re
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any, Iterable, Mapping, Sequence

from .eventlog import APPROVAL_DECISIONS, CALL_KINDS, CALL_OUTCOMES, read_jsonl
from .machine import STOP_REASONS, StopClass

SCHEMA = "atlas-metrics.v1"
#: The form `atlas create` issues. Any other run id is host-chosen text, which
#: can carry a name or a secret, so metrics show a digest of it instead.
_ISSUED_RUN_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
USAGE_KEYS: tuple[str, ...] = ("model_calls", "tool_calls", "tokens", "output_bytes")
VERDICTS: tuple[str, ...] = ("verified", "contradicted", "insufficient_evidence")
STOP_CLASSES: tuple[str, ...] = tuple(item.value for item in StopClass)


def _seconds(start: str, end: str) -> float | None:
    try:
        return round(
            (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds(), 3
        )
    except (TypeError, ValueError):
        return None


def _enum(value: Any, allowed: Iterable[str]) -> str | None:
    return value if isinstance(value, str) and value in allowed else None


def _run_id(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    if _ISSUED_RUN_ID.fullmatch(text):
        return text
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _count(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def run_metrics(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """One run's metrics from its events, in log order."""
    kinds = [record.get("kind") for record in records]
    started = next((r for r in records if r.get("kind") == "run_started"), None)
    stopped = next((r for r in records if r.get("kind") == "run_stopped"), None)
    stop = stopped.get("payload", {}) if stopped else {}

    calls: dict[str, dict[str, int]] = {}
    started_calls: dict[str, str] = {}
    for record in records:
        payload = record.get("payload", {})
        if record.get("kind") == "call_started":
            kind = _enum(payload.get("call_kind"), CALL_KINDS)
            if kind and isinstance(record.get("call_id"), str):
                started_calls[record["call_id"]] = kind
                calls.setdefault(kind, dict.fromkeys((*CALL_OUTCOMES, "unfinished"), 0))
                calls[kind]["unfinished"] += 1
        elif record.get("kind") == "call_finished":
            kind = started_calls.get(str(record.get("call_id")))
            outcome = _enum(payload.get("outcome"), CALL_OUTCOMES)
            if kind and outcome:
                calls[kind]["unfinished"] -= 1
                calls[kind][outcome] += 1

    verdicts: Counter[str] = Counter()
    for record in records:
        if record.get("kind") == "decision_recorded":
            counted = record.get("payload", {}).get("citation_verdicts")
            if isinstance(counted, Mapping):
                for verdict, number in counted.items():
                    if _enum(verdict, VERDICTS) and _count(number) is not None:
                        verdicts[verdict] += number
    checked = sum(verdicts.values())

    approvals = dict.fromkeys(APPROVAL_DECISIONS, 0)
    writes = {"verified": 0, "failed_verification": 0, "rolled_back": 0}
    for record in records:
        payload = record.get("payload", {})
        if record.get("kind") == "approval_recorded":
            decision = _enum(payload.get("decision"), APPROVAL_DECISIONS)
            if decision:
                approvals[decision] += 1
        elif record.get("kind") == "write_verified":
            writes["verified" if payload.get("verified") is True else "failed_verification"] += 1
            if payload.get("rolled_back") is True:
                writes["rolled_back"] += 1

    usage = stop.get("usage")
    iterations = [n for n in (_count(r.get("iteration")) for r in records) if n is not None]
    return {
        "run_id": _run_id(records[0].get("run_id")) if records else None,
        "kind": "run" if started else "audit",
        "finished": stopped is not None,
        "stop_reason": _enum(stop.get("stop_reason"), STOP_REASONS),
        "stop_class": _enum(stop.get("stop_class"), STOP_CLASSES),
        "latency_seconds": (
            _seconds(str(records[0].get("recorded_at")), str(stopped.get("recorded_at")))
            if stopped and records else None
        ),
        "iterations": max(iterations) if started and iterations else None,
        "events": len(kinds),
        "usage": (
            {key: _count(usage.get(key)) for key in USAGE_KEYS}
            if isinstance(usage, Mapping) else None
        ),
        "calls": calls,
        # Tool calls only: a failed model call or observation is counted in
        # `calls`, under its own kind, not as a tool error.
        "tool_errors": (
            calls["tool_call"]["failed"] + calls["tool_call"]["denied"]
            if "tool_call" in calls else 0
        ),
        "claims": {
            "checked": checked,
            **{verdict: verdicts[verdict] for verdict in VERDICTS},
            "verification_rate": round(verdicts["verified"] / checked, 4) if checked else None,
        },
        "approvals": approvals,
        "user_refusals": approvals["refused"],
        "writes": writes,
    }


def metrics(paths: Iterable[str | Path]) -> dict[str, Any]:
    """`atlas-metrics.v1` over every run in the given event logs."""
    runs: list[dict[str, Any]] = []
    for path in paths:
        by_run: dict[str, list[Mapping[str, Any]]] = {}
        for record in read_jsonl(path):
            by_run.setdefault(str(record.get("run_id")), []).append(record)
        runs.extend(run_metrics(records) for records in by_run.values())
    loop_runs = [run for run in runs if run["kind"] == "run"]
    latencies = [run["latency_seconds"] for run in loop_runs if run["latency_seconds"] is not None]
    checked = sum(run["claims"]["checked"] for run in runs)
    verified = sum(run["claims"]["verified"] for run in runs)
    return {
        "schema": SCHEMA,
        "runs": runs,
        "totals": {
            "runs": len(loop_runs),
            "audit_logs": len(runs) - len(loop_runs),
            "finished": sum(run["finished"] for run in loop_runs),
            "median_latency_seconds": round(median(latencies), 3) if latencies else None,
            "iterations": sum(run["iterations"] or 0 for run in loop_runs),
            "tokens": sum((run["usage"] or {}).get("tokens") or 0 for run in loop_runs),
            "tool_errors": sum(run["tool_errors"] for run in runs),
            "claims_checked": checked,
            "claims_contradicted": sum(run["claims"]["contradicted"] for run in runs),
            "verification_rate": round(verified / checked, 4) if checked else None,
            "user_refusals": sum(run["user_refusals"] for run in runs),
            "writes_rolled_back": sum(run["writes"]["rolled_back"] for run in runs),
        },
    }


__all__ = ["SCHEMA", "metrics", "run_metrics"]
