"""One-time guarded integration script. Delete after verified CI."""
from pathlib import Path


def replace(path: str, old: str, new: str, expected: int = 1) -> None:
    p = Path(path)
    text = p.read_text(encoding='utf-8')
    assert text.count(old) == expected, (path, text.count(old), old)
    p.write_text(text.replace(old, new), encoding='utf-8')

p = 'atlas_core/controller.py'
replace(p, 'from typing import Any, Literal, overload\n', 'from typing import Any, Callable, Literal, Mapping, overload\nimport json\n')
replace(p, 'from .budget import BudgetExceeded, RunBudget, RunLimits\n', 'from .budget import BudgetExceeded, RunBudget, RunCancelled, RunLimits\nfrom .tool_gateway import ToolDefinition, ToolGateway\n')
replace(p, '    if not isinstance(result.output, str) or not result.output.strip():\n        raise ValueError("ModelAdapter.execute returned empty output")\n', '''    if not isinstance(result.output, str) or not result.output.strip():
        raise ValueError("ModelAdapter.execute returned empty output")
    # Explicit JSON contract: malformed provider output is a runtime failure,
    # not prose that the evaluator may accidentally accept.
    if result.metadata.get("format") == "json":
        try:
            json.loads(result.output)
        except json.JSONDecodeError as exc:
            raise ValueError("ModelAdapter.execute returned malformed JSON") from exc
''')
replace(p, '        memory_adapter: MemoryAdapter | None = None,\n', '        memory_adapter: MemoryAdapter | None = None,\n        tools: Mapping[str, ToolDefinition] | None = None,\n')
replace(p, '        self.memory_adapter = memory_adapter\n', '        self.memory_adapter = memory_adapter\n        self.tools = dict(tools or {})\n')
replace(p, '        limits: RunLimits | None = ...,\n', '        limits: RunLimits | None = ...,\n        cancelled: Callable[[], bool] | None = ...,\n', expected=3)
replace(p, '        limits: RunLimits | None = None,\n    ) -> str | dict[str, Any]:\n', '        limits: RunLimits | None = None,\n        cancelled: Callable[[], bool] | None = None,\n    ) -> str | dict[str, Any]:\n')
replace(p, '''        state = AtlasRunState(task=task, max_iterations=self.max_iterations)
        budget = RunBudget(limits) if limits is not None else None
''', '''        if self.tools and limits is None:
            raise ValueError("Atlas-managed tools require RunLimits; no unmetered gateway")
        state = AtlasRunState(task=task, max_iterations=self.max_iterations)
        budget = RunBudget(limits, cancelled=cancelled) if limits is not None else None
        gateway = ToolGateway(budget=budget, tools=self.tools) if budget is not None and self.tools else None
''')
replace(p, '''        def expired() -> bool:
            if budget is None:
                return False
            try:
                budget.check()
            except BudgetExceeded as exc:
''', '''        def expired() -> bool:
            try:
                if budget is None:
                    if cancelled is not None and cancelled():
                        raise RunCancelled("cancelled")
                else:
                    budget.check()
            except RunCancelled:
                state.stop("cancelled")
                return True
            except BudgetExceeded as exc:
''')
replace(p, '''                    if budget is not None:
                        budget.reserve_model()
                        kwargs["budget"] = budget
                    model_result = self.model_adapter.execute(**kwargs)
''', '''                    if budget is not None:
                        budget.reserve_model()
                        kwargs["budget"] = budget
                    if gateway is not None:
                        kwargs["tools"] = gateway
                    model_result = self.model_adapter.execute(**kwargs)
''')
replace(p, '''                except BudgetExceeded as exc:
                    state.metadata["budget_exhausted"] = str(exc)
                    state.stop("budget_exhausted")
                    break
                except Exception as exc:
''', '''                except RunCancelled:
                    state.stop("cancelled")
                    break
                except BudgetExceeded as exc:
                    state.metadata["budget_exhausted"] = str(exc)
                    state.stop("budget_exhausted")
                    break
                except Exception as exc:
''')
replace(p, '''            if budget is not None and self.model_adapter is None:
                try:
                    budget.charge_output(output)
                except BudgetExceeded as exc:
''', '''            if budget is not None and self.model_adapter is None:
                try:
                    budget.charge_output(output)
                except RunCancelled:
                    state.stop("cancelled")
                    break
                except BudgetExceeded as exc:
''')
print('guarded P0.3 controller integration applied')
