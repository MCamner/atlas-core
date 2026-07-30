from __future__ import annotations
from .state import AtlasRunState

def finalize(state: AtlasRunState, json_mode: bool = False) -> str | dict:
    if json_mode:
        return state.to_dict()
    latest_output = state.outputs[-1] if state.outputs else "No output."
    latest_eval = state.evaluations[-1] if state.evaluations else None
    meta = [
        f"Atlas route: {state.route.name if state.route else 'unknown'}",
        f"Iterations: {state.iteration}/{state.max_iterations}",
    ]
    if latest_eval:
        meta.append(f"Quality score: {latest_eval.quality_score}")
        meta.append(f"Status: {'passed' if latest_eval.passed else 'provisional'}")
        if latest_eval.requires_user_approval:
            meta.append("Write approval required before any mutation.")
    return latest_output.rstrip() + "\n\n---\n" + "\n".join(meta) + "\n"
