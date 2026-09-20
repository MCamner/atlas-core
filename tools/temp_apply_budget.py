"""One-time patch runner; delete this file after verified integration."""
from pathlib import Path


def patch(path: str, old: str, new: str) -> None:
    p = Path(path)
    source = p.read_text(encoding="utf-8")
    assert source.count(old) == 1, (path, source.count(old), old)
    p.write_text(source.replace(old, new), encoding="utf-8")


path = "atlas_core/controller.py"
patch(path, "from .machine import classify_stop\n", "from .machine import classify_stop\nfrom .budget import BudgetExceeded, RunBudget, RunLimits\n")
patch(path, "        json_mode: Literal[False] = ...,\n", "        json_mode: Literal[False] = ...,\n        limits: RunLimits | None = ...,\n")
patch(path, "        json_mode: Literal[True],\n", "        json_mode: Literal[True],\n        limits: RunLimits | None = ...,\n")
patch(path, "        json_mode: bool,\n", "        json_mode: bool,\n        limits: RunLimits | None = ...,\n")
patch(path, "        json_mode: bool = False,\n    ) -> str | dict[str, Any]:\n", "        json_mode: bool = False,\n        limits: RunLimits | None = None,\n    ) -> str | dict[str, Any]:\n")
patch(path, "        state = AtlasRunState(task=task, max_iterations=self.max_iterations)\n", '''        state = AtlasRunState(task=task, max_iterations=self.max_iterations)
        budget = RunBudget(limits) if limits is not None else None

        def expired() -> bool:
            if budget is None:
                return False
            try:
                budget.check()
            except BudgetExceeded as exc:
                state.metadata["budget_exhausted"] = str(exc)
                state.stop("budget_exhausted")
                return True
            return False
''')
patch(path, "        while state.iteration < state.max_iterations:\n", '''        if expired():
            if budget is not None:
                state.metadata["budget_usage"] = budget.usage()
            return finalize(state, json_mode=json_mode)
        while state.iteration < state.max_iterations:
            if expired():
                break
''')
patch(path, '            state.enter("executing")\n', '            state.enter("executing")\n            if expired():\n                break\n')
patch(path, '''                    model_result = self.model_adapter.execute(
                        task=task,
                        route=route,
                        plan=plan,
                        observations=state.observations,
                        feedback=feedback,
                    )
                    _check_model_result(model_result)
''', '''                    kwargs: dict[str, Any] = dict(
                        task=task, route=route, plan=plan,
                        observations=state.observations, feedback=feedback,
                    )
                    if budget is not None:
                        budget.reserve_model()
                        kwargs["budget"] = budget
                    model_result = self.model_adapter.execute(**kwargs)
                    _check_model_result(model_result)
                    if budget is not None:
                        raw_usage = model_result.metadata.get("usage_tokens")
                        usage = int(raw_usage) if isinstance(raw_usage, str) and raw_usage.isdecimal() else None
                        budget.charge_tokens(usage)
                        budget.charge_output(model_result.output)
                except BudgetExceeded as exc:
                    state.metadata["budget_exhausted"] = str(exc)
                    state.stop("budget_exhausted")
                    break
''')
patch(path, '            state.outputs.append(output)\n', '''            if budget is not None and self.model_adapter is None:
                try:
                    budget.charge_output(output)
                except BudgetExceeded as exc:
                    state.metadata["budget_exhausted"] = str(exc)
                    state.stop("budget_exhausted")
                    break
            state.outputs.append(output)
''')
patch(path, '            state.enter("evaluating")\n', '            state.enter("evaluating")\n            if expired():\n                break\n')
patch(path, '            state.evaluations.append(evaluation)\n', '            state.evaluations.append(evaluation)\n            if expired():\n                break\n')
patch(path, '        # Only a passing run may promote a memory candidate.\n', '''        if budget is not None:
            state.metadata["budget_usage"] = budget.usage()
            # The memory writer has no deadline or tool-accounting contract.
            # A budgeted run refuses to call this unmetered side effect.
            state.metadata["memory_skipped"] = "budgeted_run_has_no_metered_memory_writer"
        # Only a passing unbudgeted run may promote a memory candidate.
''')
patch(path, '        if state.evaluations and state.stop_reason in {"passed"}:\n', '        if budget is None and state.evaluations and state.stop_reason in {"passed"}:\n')
patch("atlas_core/state.py", '''        spec = spec_for(reason)
        self.enter(spec.status)
        self.stop_reason = reason
''', '''        spec = spec_for(reason)
        if reason == "budget_exhausted":
            # A quota may trip at any stage. This is a controlled interruption,
            # not a new general-purpose enter("done") transition.
            from .machine import TERMINAL_STATUSES, InvalidTransition
            if self.status in TERMINAL_STATUSES:
                raise InvalidTransition("a terminal run cannot stop again")
            self.status = spec.status
        else:
            self.enter(spec.status)
        self.stop_reason = reason
''')
patch("tests/test_state_machine.py", '        "budget_exhausted": "P0.3 box two: wall-clock, call and token limits",\n', '')
patch("tests/test_state_machine.py", '            "no_progress",\n            "tool_error",\n', '            "no_progress",\n            "budget_exhausted",\n            "tool_error",\n')
with Path("docs/api-contract.md").open("a", encoding="utf-8") as docs:
    docs.write('''

### Optional cooperative run budget (P0.3, partial)

`AtlasController.run(..., limits=RunLimits(...))` shares one `RunBudget` with
its model adapter (`budget` keyword). Model calls, reported *actual* aggregate
`metadata["usage_tokens"]`, and UTF-8 output bytes are charged across retries.
An adapter that does not report nonnegative usage fails as `tool_error`, not a
made-up zero. The same budget exposes `reserve_tool()` for trusted nested tool
adapters, but no host tool gateway is wired yet; direct calls inside an
arbitrary Python adapter cannot be metered or sandboxed by Atlas Core.

The monotonic wall deadline is checked before and after synchronous stages.
**This is not an in-call timeout**: the model adapter itself must enforce the
passed `budget.deadline` while blocked on network/provider work. With no
adapter deadline enforcement the work can run past the wall limit before Core
regains control. A budgeted run does not call the currently unmetered memory
writer. The limits are explicit opt-in; P0.3 resource and write-safety boxes
remain open until tool integration and strict default enforcement exist.
''')
print("Budget integration source updated; run the complete suite before pushing.")
