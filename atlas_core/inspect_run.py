"""Read-only inspection of one run in an append-only Atlas event log."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .eventlog import EventLog, ResumeRefused, call_states, read_jsonl

INSPECT_SCHEMA = "atlas-inspect.v1"


class InspectError(RuntimeError):
    """The requested run cannot be reported without guessing."""


def _unique_strings(values: list[object]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value).strip()
        if text and text not in result:
            result.append(text)
    return result


def inspect_run(path: str | Path, run_id: str) -> dict[str, Any]:
    """Build a machine-readable report from one run's validated event history."""
    if not run_id:
        raise InspectError("run id cannot be empty")
    try:
        all_records = read_jsonl(path)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise InspectError(f"cannot read event log: {exc}") from exc
    if not all(isinstance(record, Mapping) for record in all_records):
        raise InspectError("event log contains a non-object record")
    records = [dict(record) for record in all_records if record.get("run_id") == run_id]
    if not records:
        raise InspectError(f"run {run_id!r} not found in event log")
    try:
        log = EventLog(run_id, previous=records)
    except (ResumeRefused, TypeError, ValueError) as exc:
        raise InspectError(f"invalid event history for {run_id!r}: {exc}") from exc

    starts = [record for record in records if record["kind"] == "run_started"]
    stops = [record for record in records if record["kind"] == "run_stopped"]
    if len(starts) != 1 or starts[0]["sequence"] != 0:
        raise InspectError("invalid event history: expected one initial run_started")
    if len(stops) > 1 or (stops and stops[0] is not records[-1]):
        raise InspectError("invalid event history: run_stopped must be unique and last")

    plans = [record for record in records if record["kind"] == "plan_selected"]
    decisions = [record for record in records if record["kind"] == "decision_recorded"]
    observations = [
        record for record in records if record["kind"] == "observation_recorded"
    ]
    sources: list[object] = []
    for record in observations:
        payload = record["payload"]
        for item in payload.get("added", []):
            if isinstance(item, Mapping):
                sources.append(item.get("source_id", ""))
        for item in payload.get("superseded", []):
            if isinstance(item, Mapping):
                sources.append(item.get("source_id", ""))
        sources.extend(payload.get("unchanged", []))

    states = call_states(log)
    unfinished = [call_id for call_id, state in states.items() if state == "unknown"]
    uncertainties: list[object] = []
    if decisions:
        latest = decisions[-1]["payload"]
        uncertainties.extend(latest.get("evidence_gaps", []))
        uncertainties.extend(latest.get("unmet_criteria", []))
    uncertainties.extend(f"call {call_id} outcome unknown" for call_id in unfinished)

    stopped = stops[0]["payload"] if stops else {}
    route = plans[-1]["payload"].get("route") if plans else None
    status = stopped.get("status") if stops else "interrupted"
    return {
        "schema": INSPECT_SCHEMA,
        "run_id": run_id,
        "status": status,
        "route": route,
        "iterations": max(record["iteration"] for record in records),
        "stop_reason": stopped.get("stop_reason"),
        "stop_class": stopped.get("stop_class"),
        "sources": _unique_strings(sources),
        "uncertainties": _unique_strings(uncertainties),
        "unfinished_calls": unfinished,
        "calls": {
            "total": len(states),
            "ok": sum(state == "ok" for state in states.values()),
            "denied": sum(state == "denied" for state in states.values()),
            "failed": sum(state == "failed" for state in states.values()),
            "unknown": len(unfinished),
        },
        "event_count": len(records),
        "started_at": records[0]["recorded_at"],
        "finished_at": records[-1]["recorded_at"] if stops else None,
        "events": records,
    }


def render_inspection(report: Mapping[str, Any]) -> str:
    """Render a compact human report; JSON remains the branching contract."""
    sources = ", ".join(report.get("sources", [])) or "none recorded"
    uncertainties = "; ".join(report.get("uncertainties", [])) or "none recorded"
    stop_reason = report.get("stop_reason") or "not stopped"
    stop_class = report.get("stop_class")
    stopped = stop_reason + (f" ({stop_class})" if stop_class else "")
    return "\n".join(
        [
            f"Run: {report['run_id']}",
            f"Status: {report.get('status') or 'unknown'}",
            f"Route: {report.get('route') or 'unknown'}",
            f"Iterations: {report.get('iterations', 0)}",
            f"Sources: {sources}",
            f"Uncertainties: {uncertainties}",
            f"Stopped: {stopped}",
        ]
    ) + "\n"


__all__ = ["INSPECT_SCHEMA", "InspectError", "inspect_run", "render_inspection"]
