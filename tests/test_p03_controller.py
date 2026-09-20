from __future__ import annotations

import json
import threading
import unittest
from typing import Any

from atlas_core.adapters.model import ModelResult, StubModelAdapter
from atlas_core.budget import RunLimits
from atlas_core.controller import AtlasController
from atlas_core.tool_gateway import ToolDefinition


def limits(**overrides: Any) -> RunLimits:
    values: dict[str, Any] = dict(wall_seconds=5, model_calls=2, tool_calls=2,
                                  tokens=100, output_bytes=10000)
    values.update(overrides)
    return RunLimits(**values)


class InvokingAdapter(StubModelAdapter):
    def __init__(self, name: str, **kwargs: Any) -> None:
        super().__init__('## Recommendation\nx\n## Next step\ny\n## Confidence\nlow\n',
                         metadata={'usage_tokens': '3'}, **kwargs)
        self.name = name

    def execute(self, **kwargs: Any) -> ModelResult:
        kwargs['tools'].invoke(self.name)
        return super().execute(**kwargs)


class TestP03Controller(unittest.TestCase):
    def test_no_unmetered_tool_configuration(self) -> None:
        tools = {'safe': ToolDefinition('safe', 'read', lambda _ctx, _args: 'ok')}
        with self.assertRaisesRegex(ValueError, 'require RunLimits'):
            AtlasController(tools=tools).run('hej', json_mode=True)

    def test_read_only_write_denied_on_execution_boundary(self) -> None:
        calls: list[str] = []
        tools = {'edit': ToolDefinition('edit', 'write', lambda _ctx, _args: calls.append('WRITE'))}
        result = AtlasController(model_adapter=InvokingAdapter('edit'), tools=tools).run(
            'review README', json_mode=True, limits=limits())
        self.assertEqual(result['stop_reason'], 'tool_error')
        self.assertEqual(result['metadata']['failure']['error'], 'ToolDenied')
        self.assertEqual(result['evaluations'], [])
        self.assertEqual(calls, [])

    def test_nested_tool_quota_propagates_through_adapter(self) -> None:
        def nesting(ctx: Any, _args: dict[str, Any]) -> str:
            ctx.invoke('child')
            ctx.invoke('child')
            return 'not reached'
        tools = {'outer': ToolDefinition('outer', 'read', nesting),
                 'child': ToolDefinition('child', 'read', lambda _ctx, _args: 'ok')}
        result = AtlasController(model_adapter=InvokingAdapter('outer'), tools=tools).run(
            'read', json_mode=True, limits=limits(tool_calls=2))
        self.assertEqual(result['stop_reason'], 'budget_exhausted')
        self.assertEqual(result['metadata']['budget_exhausted'], 'tool_calls')
        self.assertEqual(result['metadata']['budget_usage']['tool_calls'], 2)
        self.assertEqual(result['memory_candidates'], [])

    def test_immediate_abort_skips_model_and_evaluation(self) -> None:
        event = threading.Event()
        event.set()
        adapter = StubModelAdapter('ok', metadata={'usage_tokens': '1'})
        result = AtlasController(model_adapter=adapter).run(
            'read', json_mode=True, limits=limits(), cancelled=event.is_set)
        self.assertEqual(result['stop_reason'], 'cancelled')
        self.assertEqual(result['stop_class'], 'control')
        self.assertEqual(result['evaluations'], [])
        self.assertEqual(adapter.calls, [])

    def test_abort_inside_model_via_shared_budget(self) -> None:
        event = threading.Event()
        class CancellingAdapter(StubModelAdapter):
            def execute(self, **kwargs: Any) -> ModelResult:
                event.set()
                kwargs['budget'].check()
                return super().execute(**kwargs)
        result = AtlasController(model_adapter=CancellingAdapter('x')).run(
            'read', json_mode=True, limits=limits(), cancelled=event.is_set)
        self.assertEqual(result['stop_reason'], 'cancelled')
        self.assertEqual(result['memory_candidates'], [])

    def test_explicit_malformed_json_is_runtime_error(self) -> None:
        adapter = StubModelAdapter('{not-json', metadata={'usage_tokens': '1', 'format': 'json'})
        result = AtlasController(model_adapter=adapter).run('read', json_mode=True, limits=limits())
        self.assertEqual(result['stop_reason'], 'tool_error')
        self.assertEqual(result['metadata']['failure']['error'], 'ValueError')
        self.assertEqual(result['evaluations'], [])

    def test_adapter_network_failure_not_evaluation(self) -> None:
        class NetworkFailure(StubModelAdapter):
            def execute(self, **kwargs: Any) -> ModelResult:
                raise ConnectionError('network failed')
        result = AtlasController(model_adapter=NetworkFailure('x')).run('read', json_mode=True, limits=limits())
        self.assertEqual(result['stop_reason'], 'tool_error')
        self.assertEqual(result['metadata']['failure']['error'], 'ConnectionError')
        self.assertEqual(result['evaluations'], [])

    def test_iteration_bound_always_stops_unproductive_provider(self) -> None:
        adapter = StubModelAdapter('## Findings\n- impossible', metadata={'usage_tokens': '1'})
        result = AtlasController(model_adapter=adapter, max_iterations=2).run(
            'review repository', json_mode=True, limits=limits())
        self.assertLessEqual(result['iteration'], 2)
        self.assertIn(result['stop_reason'], ('no_progress', 'insufficient_evidence', 'max_iterations'))
        self.assertNotEqual(result['stop_reason'], 'passed')


if __name__ == '__main__':
    unittest.main()
