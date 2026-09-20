from __future__ import annotations

import unittest
from typing import Any

from atlas_core.budget import RunLimits
from atlas_core.adapters.model import StubModelAdapter
from atlas_core.controller import AtlasController


def limits(**kwargs: object) -> RunLimits:
    params: dict[str, Any] = dict(wall_seconds=20.0, model_calls=3, tool_calls=3, tokens=1000, output_bytes=100000)
    params.update(kwargs)
    return RunLimits(**params)


class TestBudgetedController(unittest.TestCase):
    def test_call_quota_zero_prevents_model_invocation(self):
        adapter = StubModelAdapter('whatever', metadata={'usage_tokens': '1'})
        run = AtlasController(model_adapter=adapter).run('hej', json_mode=True, limits=limits(model_calls=0))
        self.assertEqual(run['stop_reason'], 'budget_exhausted')
        self.assertEqual(adapter.calls, [])
        self.assertEqual(run['stop_class'], 'control')

    def test_unmetered_adapter_is_not_guessed_as_zero_tokens(self):
        run = AtlasController(model_adapter=StubModelAdapter('whatever')).run('hej', json_mode=True, limits=limits())
        self.assertEqual(run['stop_reason'], 'tool_error')
        self.assertEqual(run['metadata']['failure']['error'], 'UnmeteredUsage')

    def test_output_limit_stops_before_grading(self):
        run = AtlasController().run('hej', json_mode=True, limits=limits(output_bytes=1))
        self.assertEqual(run['stop_reason'], 'budget_exhausted')
        self.assertEqual(run['evaluations'], [])

    def test_reported_token_usage_is_charged(self):
        adapter = StubModelAdapter('incomplete ' * 60, metadata={'usage_tokens': '5'})
        run = AtlasController(max_iterations=2, model_adapter=adapter).run('hej', json_mode=True, limits=limits(tokens=4))
        self.assertEqual(run['stop_reason'], 'budget_exhausted')
        self.assertEqual(run['metadata']['budget_usage']['tokens'], 5)
        self.assertEqual(run['memory_candidates'], [])

    def test_metered_run_records_usage_but_does_not_write_unmetered_memory(self):
        adapter = StubModelAdapter('## Recommendation\nx\n## Next step\ny\n## Confidence\nHigh.\n' + 'text ' * 80, metadata={'usage_tokens': '10'})
        run = AtlasController(model_adapter=adapter).run('hej', json_mode=True, limits=limits())
        self.assertEqual(run['stop_reason'], 'passed')
        self.assertEqual(run['metadata']['budget_usage']['model_calls'], 1)
        self.assertEqual(run['metadata']['memory_skipped'], 'budgeted_run_has_no_metered_memory_writer')


if __name__ == '__main__':
    unittest.main()
