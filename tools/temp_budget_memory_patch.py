"""One-time fix; remove before merging."""
from pathlib import Path

p = Path('atlas_core/controller.py')
s = p.read_text(encoding='utf-8')
old = '''        if self.memory_adapter:
            state.observations.extend(self.memory_adapter.read(task))
'''
new = '''        # No unmetered reads from host adapters in resource-limited runs.
        if self.memory_adapter and budget is None:
            state.observations.extend(self.memory_adapter.read(task))
        elif self.memory_adapter:
            state.metadata["memory_read_skipped"] = "budgeted_run_has_no_metered_memory_reader"
'''
assert s.count(old) == 1, s.count(old)
p.write_text(s.replace(old,new),encoding='utf-8')
p = Path('tests/test_budget_controller.py')
s = p.read_text(encoding='utf-8')
anchor = 'class TestBudgetedController(unittest.TestCase):\n'
newtest = '''class ExplodingMemory:
    def read(self, query: str) -> list[str]:
        raise AssertionError("unmetered memory read must not run")
    def write(self, record: dict) -> str | None:
        raise AssertionError("unmetered memory write must not run")


class TestBudgetedController(unittest.TestCase):
    def test_unmetered_memory_is_not_invoked(self):
        run = AtlasController(memory_adapter=ExplodingMemory()).run('hej', json_mode=True, limits=limits())
        self.assertEqual(run['stop_reason'], 'passed')
        self.assertEqual(run['metadata']['memory_read_skipped'], 'budgeted_run_has_no_metered_memory_reader')
        self.assertEqual(run['memory_candidates'], [])
'''
assert s.count(anchor) == 1
p.write_text(s.replace(anchor,newtest),encoding='utf-8')
