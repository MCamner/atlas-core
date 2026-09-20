"""A hard timeout must terminate a genuinely noncooperative Python adapter."""
from __future__ import annotations

import os
import time
import unittest
from typing import Any

from atlas_core import AtlasController, run_isolated
from atlas_core.adapters.model import ModelResult, StubModelAdapter
from atlas_core.budget import RunLimits
from atlas_core.tool_gateway import ToolContext, ToolDefinition


class HangingAdapter:
    def execute(self, **_kwargs: Any) -> ModelResult:
        time.sleep(30)
        return ModelResult(output='this must never be promoted', metadata={'usage_tokens': '1'})


class RaisingAdapter:
    def execute(self, **_kwargs: Any) -> ModelResult:
        raise ConnectionError('provider unavailable')


class NestedAdapter:
    def execute(self, **kwargs: Any) -> ModelResult:
        kwargs['tools'].invoke('outer')
        return ModelResult(output='## Recommendation\nread\n## Next step\nreview\n## Confidence\nLow\n',
                           metadata={'usage_tokens': '1'})


def outer(context: ToolContext, _args: dict[str, Any]) -> str:
    return context.invoke('inner')


def inner(_context: ToolContext, _args: dict[str, Any]) -> str:
    return 'read only'


@unittest.skipUnless(os.name == 'posix', 'POSIX process isolation')
class TestIsolatedController(unittest.TestCase):
    def test_hung_python_adapter_is_killed_without_evaluation(self) -> None:
        started = time.monotonic()
        result = run_isolated(
            AtlasController(model_adapter=HangingAdapter()), 'read only',
            limits=RunLimits(0.5, 1, 0, 5, 1024),
        )
        self.assertEqual(result['stop_reason'], 'budget_exhausted')
        self.assertEqual(result['metadata']['budget_exhausted'], 'wall_seconds')
        self.assertEqual(result['evaluations'], [])
        self.assertEqual(result['memory_candidates'], [])
        self.assertLess(time.monotonic() - started, 4.0)

    def test_parent_can_cancel_hung_adapter(self) -> None:
        started = time.monotonic()
        result = run_isolated(
            AtlasController(model_adapter=HangingAdapter()), 'read only',
            limits=RunLimits(8, 1, 0, 5, 1024),
            cancelled=lambda: time.monotonic() - started >= .25,
        )
        self.assertEqual(result['stop_reason'], 'cancelled')
        self.assertEqual(result['evaluations'], [])
        self.assertLess(time.monotonic() - started, 4.0)

    def test_nested_calls_cannot_reset_run_budget(self) -> None:
        tools = {
            'outer': ToolDefinition('outer', 'read', outer),
            'inner': ToolDefinition('inner', 'read', inner),
        }
        result = run_isolated(
            AtlasController(model_adapter=NestedAdapter(), tools=tools), 'read only',
            limits=RunLimits(5, 1, 1, 5, 4096),
        )
        self.assertEqual(result['stop_reason'], 'budget_exhausted')
        self.assertEqual(result['metadata']['budget_exhausted'], 'tool_calls')
        self.assertEqual(result['metadata']['budget_usage']['tool_calls'], 1)
        self.assertEqual(result['evaluations'], [])

    def test_nested_reads_share_one_budget_when_allowed(self) -> None:
        tools = {
            'outer': ToolDefinition('outer', 'read', outer),
            'inner': ToolDefinition('inner', 'read', inner),
        }
        result = run_isolated(
            AtlasController(model_adapter=NestedAdapter(), tools=tools), 'read only',
            limits=RunLimits(5, 1, 2, 5, 4096),
        )
        self.assertEqual(result['metadata']['budget_usage']['tool_calls'], 2)
        self.assertEqual(result['metadata']['budget_usage']['model_calls'], 1)
        self.assertEqual(result['metadata']['isolation'], 'spawned_process')
        self.assertNotEqual(result['stop_reason'], 'tool_error')

    def test_unpicklable_model_fails_closed(self) -> None:
        class UnpicklableAdapter:
            def execute(self, **_kwargs: Any) -> ModelResult:
                return ModelResult(output='wrong', metadata={'usage_tokens': '1'})
        result = run_isolated(
            AtlasController(model_adapter=UnpicklableAdapter()), 'read only',
            limits=RunLimits(5, 1, 0, 5, 1024),
        )
        self.assertEqual(result['stop_reason'], 'tool_error')
        self.assertEqual(result['evaluations'], [])

    def test_provider_error_does_not_promote_fallback(self) -> None:
        result = run_isolated(
            AtlasController(model_adapter=RaisingAdapter()), 'read only',
            limits=RunLimits(5, 1, 0, 5, 1024),
        )
        self.assertEqual(result['stop_reason'], 'tool_error')
        self.assertEqual(result['evaluations'], [])

    def test_stub_adapter_runs_in_separate_process(self) -> None:
        result = run_isolated(
            AtlasController(model_adapter=StubModelAdapter(
                '## Recommendation\nread\n## Next step\nreview\n## Confidence\nLow\n',
                metadata={'usage_tokens': '1'})),
            'read only', limits=RunLimits(5, 1, 0, 5, 4096),
        )
        self.assertEqual(result['metadata']['isolation'], 'spawned_process')
        self.assertEqual(result['metadata']['budget_usage']['model_calls'], 1)
        self.assertNotEqual(result['stop_reason'], 'tool_error')


if __name__ == '__main__':
    unittest.main()
