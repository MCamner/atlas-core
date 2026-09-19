from __future__ import annotations
from .state import AtlasRunState
from .router import select_route
from .planner import build_plan
from .executor import execute_plan
from .evaluator import evaluate
from .finalizer import finalize
from .memory import build_memory_candidate, save_local_memory
from .safety import safety_notice
from .adapters.model import ModelAdapter
from .adapters.base import MemoryAdapter

class AtlasController:
    def __init__(
        self,
        max_iterations: int = 2,
        memory_dir: str | None = None,
        model_adapter: ModelAdapter | None = None,
        memory_adapter: MemoryAdapter | None = None,
    ):
        self.max_iterations = max_iterations
        self.memory_dir = memory_dir
        self.model_adapter = model_adapter
        self.memory_adapter = memory_adapter

    def run(self, task: str, *, observations: list[str] | None = None, json_mode: bool = False):
        state = AtlasRunState(task=task, max_iterations=self.max_iterations)
        state.status = "observing"
        # Copy: the caller's list must not grow as a side effect of a run.
        state.observations.extend(list(observations or []))
        if self.memory_adapter:
            state.observations.extend(self.memory_adapter.read(task))
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
            if self.model_adapter:
                model_result = self.model_adapter.execute(
                    task=task,
                    route=route,
                    plan=plan,
                    observations=state.observations,
                    feedback=feedback,
                )
                output = model_result.output
                state.metadata["model_result"] = {
                    "provider": model_result.provider,
                    "model": model_result.model,
                    "metadata": model_result.metadata,
                }
            else:
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
            if self.memory_adapter:
                saved_path = self.memory_adapter.write(candidate)
            else:
                saved_path = save_local_memory(self.memory_dir, candidate)
            if saved_path:
                candidate["saved_path"] = saved_path
            state.memory_candidates.append(candidate)
        return finalize(state, json_mode=json_mode)
