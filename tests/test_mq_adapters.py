from __future__ import annotations

import unittest
from typing import Any

from atlas_core.adapters.mq import (
    MQAgentAdapter,
    MQMCPAdapter,
    MQToolContract,
)
from atlas_core.budget import RunBudget, RunLimits
from atlas_core.tool_gateway import ToolDenied, ToolGateway


class _Client:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        self.calls.append((name, arguments))
        return {"tool": name, "arguments": arguments}


def _budget() -> RunBudget:
    return RunBudget(RunLimits(10, 0, 4, 0, 4_000))


class TestMQMCPAdapter(unittest.TestCase):
    def test_exposes_only_explicit_read_only_contracts(self) -> None:
        client = _Client()
        adapter = MQMCPAdapter(
            client,
            contracts=[
                MQToolContract(
                    name="read_repo_file",
                    safety_class="read-only",
                    input_schema={
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                        "required": ["path"],
                        "additionalProperties": False,
                    },
                    output_schema={"type": "object"},
                )
            ],
        )
        gateway = ToolGateway(budget=_budget(), tools=adapter.tools())

        result = gateway.invoke("read_repo_file", {"path": "README.md"})

        self.assertEqual(result["tool"], "read_repo_file")
        self.assertEqual(client.calls, [("read_repo_file", {"path": "README.md"})])
        with self.assertRaises(ToolDenied):
            gateway.invoke("write_repo_file", {"path": "README.md"})

    def test_rejects_non_read_only_or_unknown_contracts_at_registration(self) -> None:
        for safety_class in ("write-capable", "subprocess", "dangerous", "unknown"):
            with self.subTest(safety_class=safety_class), self.assertRaises(ValueError):
                MQMCPAdapter(
                    _Client(),
                    contracts=[MQToolContract("tool", safety_class=safety_class)],
                )

    def test_receiver_gate_fails_closed_before_transport_call(self) -> None:
        client = _Client()
        adapter = MQMCPAdapter(
            client,
            contracts=[MQToolContract("read_repo_file", safety_class="read-only")],
            receiver_ready=lambda: False,
        )
        gateway = ToolGateway(budget=_budget(), tools=adapter.tools())

        with self.assertRaisesRegex(ToolDenied, "receiver gate"):
            gateway.invoke("read_repo_file")
        self.assertEqual(client.calls, [])


class TestMQAgentAdapter(unittest.TestCase):
    def test_handoff_is_read_only_and_returns_an_observation(self) -> None:
        client = _Client()
        adapter = MQAgentAdapter(
            client,
            contracts=[MQToolContract("repo_summary", safety_class="read-only")],
        )

        observations = adapter.observe("review dependencies")

        self.assertEqual(client.calls, [("repo_summary", {"task": "review dependencies"})])
        self.assertEqual(len(observations), 1)
        self.assertIn("MQ agent read-only observation", observations[0])
        self.assertIn('"tool": "repo_summary"', observations[0])

    def test_handoff_requires_an_explicit_operation_allowlist(self) -> None:
        with self.assertRaises(ValueError):
            MQAgentAdapter(_Client(), contracts=[])
        with self.assertRaises(ValueError):
            MQAgentAdapter(
                _Client(),
                contracts=[
                    MQToolContract("repo_summary", safety_class="read-only"),
                    MQToolContract("repo_summary", safety_class="read-only"),
                ],
            )
        with self.assertRaises(ValueError):
            MQAgentAdapter(
                _Client(),
                contracts=[MQToolContract("release", safety_class="write-capable")],
            )


if __name__ == "__main__":
    unittest.main()
