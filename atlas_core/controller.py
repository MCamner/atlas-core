from __future__ import annotations
from .state import AtlasRunState
from .router import select_route
from .planner import build_plan
from .executor import execute_plan
from .evaluator import evaluate
from .finalizer import finalize
from .memory import build_memory_candidate, save_local_memory
from .safety import safety_notice

class AtlasController:
    def __init__(self, max_iterations: int = 2, memory_dir: str | None = None):
        self.max_iterations = max_iterations
        self.memory_dir = memory_dir

    def run(self, task: str, *, observations: list[str] | None = None, json_mode: bool = False):
        state = AtlasRunState(task=task, max_iterations=self.max_iterations)
        state.status = "observing"
        # Copy: the caller's list must not grow as a side effect of a run.
        state.observations.extend(list(observations or []))
        notice = safety_notice(task)
        if notice:
            # A warning is not a source, so it stays out of the observation list
            # the executor renders under "Sources inspected".
            state.metadata["safety_notice"] = notice

        while state.iteration < state.max_iterations:
            state.iteration += 1
            state.status = "routing"
            route = select_route(task)
            state.route = route
            state.status = "planning"
            plan = build_plan(task, route)
            state.plan = plan
            state.status = "executing"
            # The previous evaluation is what makes a retry a replan rather than
            # a rerun: it tells the executor which gaps to close this time.
            feedback = state.evaluations[-1] if state.evaluations else None
            output = execute_plan(task, plan, state.observations, feedback=feedback)
            state.outputs.append(output)
            state.status = "evaluating"
            evaluation = evaluate(task, output, plan.validation_focus, state.iteration, state.max_iterations)
            state.evaluations.append(evaluation)
            if evaluation.requires_user_approval:
                state.status = "need_user_approval"
                break
            if evaluation.passed or not evaluation.should_retry:
                state.status = "done"
                break
            state.status = "replanning"

        if state.evaluations:
            candidate = build_memory_candidate(
                task=state.task,
                route_name=state.route.name if state.route else "unknown",
                output=state.outputs[-1] if state.outputs else "",
                quality_score=state.evaluations[-1].quality_score,
            )
            saved_path = save_local_memory(self.memory_dir, candidate)
            if saved_path:
                candidate["saved_path"] = saved_path
            state.memory_candidates.append(candidate)
        return finalize(state, json_mode=json_mode)
