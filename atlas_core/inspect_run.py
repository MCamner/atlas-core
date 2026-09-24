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


def _payload_list(
    payload: Mapping[str, Any], field: str, *, kind: str
) -> list[object]:
    value = payload.get(field, [])
    if not isinstance(value, list):
        raise InspectError(
            f"invalid event history: {kind}.{field} must be a list"
        )
    return value


def _nonempty_text(value: object, *, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InspectError(f"invalid event history: {where} must be non-empty text")
    return value


def _validate_history(records: list[dict[str, Any]], run_id: str) -> EventLog:
    """Validate relationships between individually valid events.

    EventLog validates the event envelope. Inspection also has to validate
    cross-event claims: event identity, call pairing and the payload shapes it
    derives the report from. Otherwise a contradictory history could be
    silently summarized into something cleaner than the log actually says.
    """
    try:
        log = EventLog(run_id, previous=records)
    except (ResumeRefused, TypeError, ValueError) as exc:
        raise InspectError(f"invalid event history for {run_id!r}: {exc}") from exc

    for record in records:
        sequence = record["sequence"]
        expected_event_id = f"{run_id}:{sequence}"
        if record.get("event_id") != expected_event_id:
            raise InspectError(
                "invalid event history: event_id does not match run_id and sequence"
            )

    starts = [record for record in records if record["kind"] == "run_started"]
    stops = [record for record in records if record["kind"] == "run_stopped"]
    if len(starts) != 1 or starts[0]["sequence"] != 0:
        raise InspectError("invalid event history: expected one initial run_started")
    if len(stops) > 1 or (stops and stops[0] is not records[-1]):
        raise InspectError("invalid event history: run_stopped must be unique and last")

    started_calls: set[str] = set()
    finished_calls: set[str] = set()
    for record in records:
        kind = record["kind"]
        payload = record["payload"]

        if kind == "call_started":
            call_id = _nonempty_text(record.get("call_id"), where="call_started.call_id")
            if call_id != f"{run_id}:{record['sequence']}":
                raise InspectError(
                    "invalid event history: call_id does not identify its start event"
                )
            if call_id in started_calls:
                raise InspectError("invalid event history: duplicate call_started")
            started_calls.add(call_id)

        elif kind == "call_finished":
            call_id = _nonempty_text(record.get("call_id"), where="call_finished.call_id")
            if call_id not in started_calls:
                raise InspectError(
                    "invalid event history: call_finished has no preceding call_started"
                )
            if call_id in finished_calls:
                raise InspectError(
                    "invalid event history: a call has more than one outcome"
                )
            finished_calls.add(call_id)

        elif kind == "observation_recorded":
            for field in ("added", "superseded"):
                for item in _payload_list(payload, field, kind=kind):
                    if not isinstance(item, Mapping):
                        raise InspectError(
                            f"invalid event history: {kind}.{field} items must be objects"
                        )
                    _nonempty_text(
                        item.get("source_id"),
                        where=f"{kind}.{field}.source_id",
                    )
            for item in _payload_list(payload, "unchanged", kind=kind):
                _nonempty_text(item, where=f"{kind}.unchanged item")

        elif kind == "decision_recorded":
            for field in ("evidence_gaps", "unmet_criteria"):
                for item in _payload_list(payload, field, kind=kind):
                    _nonempty_text(item, where=f"{kind}.{field} item")

        elif kind == "plan_selected":
            route = payload.get("route")
            if route is not None:
                _nonempty_text(route, where="plan_selected.route")

        elif kind == "run_stopped":
            _nonempty_text(payload.get("status"), where="run_stopped.status")
            _nonempty_text(
                payload.get("stop_reason"), where="run_stopped.stop_reason"
            )
            _nonempty_text(payload.get("stop_class"), where="run_stopped.stop_class")

    return log


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
    log = _validate_history(records, run_id)
    starts = [record for record in records if record["kind"] == "run_started"]
    stops = [record for record in records if record["kind"] == "run_stopped"]

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
