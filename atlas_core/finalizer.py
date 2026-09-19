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
    if json_mode:
        return state.to_dict()
    latest_output = state.outputs[-1] if state.outputs else "No output."
    latest_eval = state.evaluations[-1] if state.evaluations else None
    meta = [
        f"Atlas route: {state.route.name if state.route else 'unknown'}",
        f"Iterations: {state.iteration}/{state.max_iterations}",
        f"Stop reason: {state.stop_reason or 'unknown'}",
    ]
    if latest_eval:
        meta.append(f"Quality score: {latest_eval.quality_score}")
        meta.append(f"Status: {'passed' if latest_eval.passed else 'provisional'}")
        if latest_eval.requires_user_approval:
            meta.append("Write approval required before any mutation.")
    return latest_output.rstrip() + "\n\n---\n" + "\n".join(meta) + "\n"
