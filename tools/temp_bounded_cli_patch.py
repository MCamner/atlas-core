"""One-time guarded patch; delete before merging."""
from pathlib import Path
import json


def patch(path: str, old: str, new: str, count: int = 1) -> None:
    p = Path(path)
    text = p.read_text(encoding='utf-8')
    assert text.count(old) == count, (path, text.count(old), old[:180])
    p.write_text(text.replace(old, new), encoding='utf-8')

c = 'atlas_core/controller.py'
patch(c, '        cancelled: Callable[[], bool] | None = ...,\n', '        cancelled: Callable[[], bool] | None = ...,\n        readers: list[Callable[[str, RunBudget], list[str]]] | None = ...,\n', 3)
patch(c, '        cancelled: Callable[[], bool] | None = None,\n    ) -> str | dict[str, Any]:\n', '        cancelled: Callable[[], bool] | None = None,\n        readers: list[Callable[[str, RunBudget], list[str]]] | None = None,\n    ) -> str | dict[str, Any]:\n')
patch(c, '        if self.tools and limits is None:\n            raise ValueError("Atlas-managed tools require RunLimits; no unmetered gateway")\n', '''        if self.tools and limits is None:
            raise ValueError("Atlas-managed tools require RunLimits; no unmetered gateway")
        if readers and limits is None:
            raise ValueError("Atlas-managed readers require RunLimits")
''')
patch(c, '''        state.evidence_base = evidence
        # No unmetered reads from host adapters in resource-limited runs.
''', '''        state.evidence_base = evidence
        if readers:
            assert budget is not None  # checked at entry: no unmetered readers
            try:
                for reader in readers:
                    budget.check()
                    gathered = reader(task, budget)
                    if not isinstance(gathered, list) or any(
                        not isinstance(item, str) for item in gathered
                    ):
                        raise TypeError("source reader must return list[str]")
                    budget.charge_output("\\n".join(gathered))
                    state.observations.extend(gathered)
            except RunCancelled:
                state.stop("cancelled")
            except BudgetExceeded as exc:
                state.metadata["budget_exhausted"] = str(exc)
                state.stop("budget_exhausted")
            except Exception as exc:
                state.stop("tool_error")
                state.metadata["failure"] = {
                    "stage": "observer",
                    "error": type(exc).__name__,
                    "message": str(exc)[:MAX_FAILURE_MESSAGE],
                }
            if state.stop_reason is not None:
                state.metadata["budget_usage"] = budget.usage()
                return finalize(state, json_mode=json_mode)
        # No unmetered reads from host adapters in resource-limited runs.
''')
m='atlas_core/machine.py'
patch(m, '_INTERRUPTIONS: frozenset[str] = frozenset({"failed", "cancelled"})', '''# Control bounds can stop while observing, routing or planning, not only
# after the evaluator. Add done to working-state interruptions; terminal
# states remain immutable. Both Python and the published table must agree.
_INTERRUPTIONS: frozenset[str] = frozenset({"done", "failed", "cancelled"})''')
schema = Path('schemas/atlas-state-machine.v1.json')
data = json.loads(schema.read_text(encoding='utf-8'))
for name, targets in data['transitions'].items():
    if name not in data['terminal_statuses'] and 'done' not in targets:
        targets.append('done')
        targets.sort()
schema.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
print('controller reader gate and early-budget state transition integrated')
