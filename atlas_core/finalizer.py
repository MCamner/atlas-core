from __future__ import annotations
from typing import Any, Literal, overload

from .state import AtlasRunState


@overload
def finalize(state: AtlasRunState, json_mode: Literal[False] = ...) -> str: ...


@overload
def finalize(state: AtlasRunState, json_mode: Literal[True]) -> dict[str, Any]: ...


@overload
def finalize(state: AtlasRunState, json_mode: bool) -> str | dict[str, Any]: ...


def finalize(state: AtlasRunState, json_mode: bool = False) -> str | dict[str, Any]:
    run = state.to_dict()
    return run if json_mode else render_run_text(run)


def render_run_text(run: dict[str, Any]) -> str:
    """Render an `atlas-run.v1` document as the text a human reads.

    The text trailer is a rendering of the run document, not a second source of
    truth. Anything a caller needs to branch on is in the document; parsing this
    prose to find it is what the API contract tells adapters not to do.
    """
    outputs = run.get("outputs") or []
    evaluations = run.get("evaluations") or []
    route = run.get("route") or {}
    latest_output = outputs[-1] if outputs else "No output."
    latest_eval = evaluations[-1] if evaluations else None
    meta = [
        f"Atlas route: {route.get('name') or 'unknown'}",
        f"Iterations: {run.get('iteration', 0)}/{run.get('max_iterations', 0)}",
        f"Stop reason: {run.get('stop_reason') or 'unknown'}",
    ]
    if latest_eval:
        meta.append(f"Quality score: {latest_eval['quality_score']}")
        meta.append(f"Status: {'passed' if latest_eval['passed'] else 'provisional'}")
        if latest_eval.get("evidence_gaps"):
            meta.append("Evidence gaps: " + ", ".join(latest_eval["evidence_gaps"]))
        if latest_eval["requires_user_approval"]:
            meta.append("Write approval required before any mutation.")
    if run.get("stop_reason") == "failed":
        failure = (run.get("metadata") or {}).get("failure") or {}
        meta.append(
            f"Failure: {failure.get('stage', 'unknown')} raised "
            f"{failure.get('error', 'an error')}."
        )
    return latest_output.rstrip() + "\n\n---\n" + "\n".join(meta) + "\n"
