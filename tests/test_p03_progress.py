from __future__ import annotations

import unittest

from atlas_core.adapters.model import StubModelAdapter
from atlas_core.budget import RunLimits
from atlas_core.controller import AtlasController


class TestUnproductiveLoops(unittest.TestCase):
    def test_identical_model_output_stops_no_progress_after_second_iteration(self) -> None:
        adapter = StubModelAdapter('identical incomplete response', metadata={'usage_tokens': '1'})
        result = AtlasController(max_iterations=10, model_adapter=adapter).run(
            'summarize a short note', json_mode=True,
            limits=RunLimits(wall_seconds=10, model_calls=10, tool_calls=0,
                             tokens=100, output_bytes=10000))
        self.assertEqual(result['stop_reason'], 'no_progress')
        self.assertEqual(result['iteration'], 2)
        self.assertEqual(result['metadata']['no_progress']['reason'], 'identical_model_output')
        self.assertEqual(result['metadata']['budget_usage']['model_calls'], 2)
        self.assertEqual(len(result['evaluations']), 2)
        self.assertTrue(result['evaluations'][-1]['missing_sections'])
        self.assertEqual(result['memory_candidates'], [])

    def test_repeated_output_stops_when_iteration_bound_equals_two(self) -> None:
        adapter = StubModelAdapter('same incomplete response', metadata={'usage_tokens': '1'})
        result = AtlasController(max_iterations=2, model_adapter=adapter).run(
            'summarize a short note', json_mode=True,
            limits=RunLimits(10, 2, 0, 100, 10000))
        self.assertEqual(result['stop_reason'], 'no_progress')
        self.assertEqual(result['iteration'], 2)


if __name__ == '__main__':
    unittest.main()
