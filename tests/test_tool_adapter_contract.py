from __future__ import annotations

import os
import time
import unittest
from typing import Any

from atlas_core.budget import BudgetExceeded, RunBudget, RunLimits
from atlas_core.eventlog import EventLog, call_states
from atlas_core.tool_gateway import (
    ToolDefinition,
    ToolDenied,
    ToolGateway,
    ToolSchemaError,
    ToolTimeout,
)


def _budget(tool_calls: int = 5) -> RunBudget:
    return RunBudget(RunLimits(5, 1, tool_calls, 100, 10_000))


class TestToolAdapterContract(unittest.TestCase):
    def test_route_allowlist_denies_before_handler_and_budget(self) -> None:
        touched: list[str] = []
        tool = ToolDefinition(
            "read_file", "read", lambda _c, _a: touched.append("ran"),
            allowed_routes=("repo_review",),
        )
        gateway = ToolGateway(budget=_budget(), tools={tool.name: tool})
        gateway.set_route("general")

        with self.assertRaisesRegex(ToolDenied, "route"):
            gateway.invoke("read_file")

        self.assertEqual(touched, [])
        self.assertEqual(gateway.budget.tool_calls, 0)

    def test_input_and_output_must_match_declared_schemas(self) -> None:
        tool = ToolDefinition(
            "line_count",
            "read",
            lambda _c, args: {"count": len(args["text"].splitlines())},
            input_schema={
                "type": "object",
                "required": ["text"],
                "properties": {"text": {"type": "string"}},
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "required": ["count"],
                "properties": {"count": {"type": "integer"}},
                "additionalProperties": False,
            },
        )
        gateway = ToolGateway(budget=_budget(), tools={tool.name: tool})

        with self.assertRaisesRegex(ToolSchemaError, "input"):
            gateway.invoke("line_count", {"wrong": "x"})
        self.assertEqual(gateway.invoke("line_count", {"text": "a\nb"}), {"count": 2})

        broken = ToolDefinition(
            "broken", "read", lambda _c, _a: {"count": "two"},
            output_schema=tool.output_schema,
        )
        with self.assertRaisesRegex(ToolSchemaError, "output"):
            ToolGateway(budget=_budget(), tools={"broken": broken}).invoke("broken")

    def test_retries_require_explicit_idempotence_and_share_budget(self) -> None:
        with self.assertRaisesRegex(ValueError, "idempotent"):
            ToolDefinition(
                "unsafe", "read", lambda _c, _a: "x",
                idempotent=False, max_attempts=2,
            )

        attempts = [0]

        def flaky(_context: Any, _arguments: dict[str, Any]) -> str:
            attempts[0] += 1
            if attempts[0] < 3:
                raise OSError("temporary")
            return "ok"

        tool = ToolDefinition(
            "flaky", "read", flaky,
            idempotent=True, max_attempts=3, retry_on=(OSError,),
        )
        gateway = ToolGateway(budget=_budget(3), tools={tool.name: tool})

        self.assertEqual(gateway.invoke("flaky"), "ok")
        self.assertEqual(attempts, [3])
        self.assertEqual(gateway.budget.tool_calls, 3)

        attempts[0] = 0
        with self.assertRaisesRegex(BudgetExceeded, "tool_calls"):
            ToolGateway(budget=_budget(2), tools={tool.name: tool}).invoke("flaky")
        self.assertEqual(attempts, [2])

    def test_each_retry_is_a_separate_idempotent_event_call(self) -> None:
        class Sink:
            def __init__(self) -> None:
                self.records: list[dict[str, Any]] = []

            def write(self, record: Any) -> None:
                self.records.append(dict(record))

        attempts = [0]

        def flaky(_context: Any, _arguments: dict[str, Any]) -> str:
            attempts[0] += 1
            if attempts[0] == 1:
                raise OSError("again")
            return "ok"

        sink = Sink()
        tool = ToolDefinition(
            "logged_retry", "read", flaky,
            idempotent=True, max_attempts=2, retry_on=(OSError,),
        )
        gateway = ToolGateway(
            budget=_budget(2), tools={tool.name: tool}, log=EventLog("run-1", sink)
        )

        self.assertEqual(gateway.invoke(tool.name), "ok")

        starts = [record for record in sink.records if record["kind"] == "call_started"]
        self.assertEqual([record["payload"]["attempt"] for record in starts], [1, 2])
        self.assertTrue(all(record["payload"]["idempotent"] for record in starts))
        self.assertEqual(list(call_states(sink.records).values()), ["failed", "ok"])

    @unittest.skipUnless(os.name == "posix", "isolated tools require POSIX")
    def test_isolated_process_enforces_hard_timeout(self) -> None:
        def stuck(_context: Any, _arguments: dict[str, Any]) -> str:
            time.sleep(2)
            return "late"

        tool = ToolDefinition(
            "stuck", "read", stuck,
            timeout_seconds=0.05, sandbox="isolated_process",
        )
        started = time.monotonic()

        with self.assertRaises(ToolTimeout):
            ToolGateway(budget=_budget(), tools={tool.name: tool}).invoke("stuck")

        self.assertLess(time.monotonic() - started, 1.0)

    @unittest.skipUnless(os.name == "posix", "isolated tools require POSIX")
    def test_isolated_idempotent_failure_can_retry(self) -> None:
        marker = os.path.join(self.id(), "unused")

        def fail_once(_context: Any, arguments: dict[str, Any]) -> str:
            path = arguments["path"]
            if not os.path.exists(path):
                open(path, "w", encoding="utf-8").close()
                raise OSError("temporary")
            return "ok"

        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, marker.replace("/", "_"))
            tool = ToolDefinition(
                "isolated_retry", "read", fail_once,
                sandbox="isolated_process", idempotent=True,
                max_attempts=2, retry_on=(OSError,),
            )

            result = ToolGateway(
                budget=_budget(2), tools={tool.name: tool}
            ).invoke(tool.name, {"path": path})

        self.assertEqual(result, "ok")
