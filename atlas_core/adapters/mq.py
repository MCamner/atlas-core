"""Optional, dependency-free boundaries for MQ read-only integrations."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from typing import Any, Callable, Mapping, Protocol, Sequence

from ..tool_gateway import ToolDefinition, ToolDenied


class MQToolClient(Protocol):
    """Small transport surface implemented by mq-agent and mq-mcp clients."""

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any: ...


@dataclass(frozen=True)
class MQToolContract:
    """The caller-facing subset of an MQ tool contract Atlas accepts."""

    name: str
    safety_class: str
    input_schema: Mapping[str, Any] = field(default_factory=lambda: {"type": "object"})
    output_schema: Mapping[str, Any] = field(default_factory=dict)
    allowed_routes: tuple[str, ...] = ("*",)
    timeout_seconds: float = 5.0


class MQMCPAdapter:
    """Project explicitly selected mq-mcp read tools into Atlas' gateway."""

    def __init__(
        self,
        client: MQToolClient,
        *,
        contracts: Sequence[MQToolContract],
        receiver_ready: Callable[[], bool] | None = None,
    ) -> None:
        if not contracts:
            raise ValueError("at least one mq-mcp tool contract is required")
        names = [contract.name for contract in contracts]
        if len(names) != len(set(names)):
            raise ValueError("mq-mcp tool contracts must have unique names")
        for contract in contracts:
            if contract.safety_class != "read-only":
                raise ValueError(
                    f"mq-mcp tool {contract.name!r} is not declared read-only"
                )
        self._client = client
        self._contracts = tuple(contracts)
        self._receiver_ready = receiver_ready

    def _handler(self, name: str) -> Callable[[Any, dict[str, Any]], Any]:
        def call(_context: Any, arguments: dict[str, Any]) -> Any:
            if self._receiver_ready is not None and not self._receiver_ready():
                raise ToolDenied("mq-mcp receiver gate refused the call")
            return self._client.call_tool(name, arguments)

        return call

    def tools(self) -> dict[str, ToolDefinition]:
        return {
            contract.name: ToolDefinition(
                name=contract.name,
                capability="read",
                handler=self._handler(contract.name),
                allowed_routes=contract.allowed_routes,
                input_schema=contract.input_schema,
                output_schema=contract.output_schema,
                timeout_seconds=contract.timeout_seconds,
                idempotent=True,
            )
            for contract in self._contracts
        }


class MQAgentAdapter:
    """Use mq-agent as a read-only observation handoff, never as loop owner."""

    def __init__(
        self,
        client: MQToolClient,
        *,
        contracts: Sequence[MQToolContract],
        receiver_ready: Callable[[], bool] | None = None,
    ) -> None:
        names = [contract.name for contract in contracts]
        if not names or len(names) != len(set(names)):
            raise ValueError("contracts must be a non-empty unique allowlist")
        if any(not re.fullmatch(r"[a-z][a-z0-9_]*", name) for name in names):
            raise ValueError("operation names must be lowercase literals")
        if any(contract.safety_class != "read-only" for contract in contracts):
            raise ValueError("mq-agent operations must be declared read-only")
        self._client = client
        self._operations = tuple(names)
        self._receiver_ready = receiver_ready

    def observe(self, task: str) -> list[str]:
        if self._receiver_ready is not None and not self._receiver_ready():
            raise ToolDenied("mq-agent receiver gate refused the handoff")
        observations: list[str] = []
        for operation in self._operations:
            result = self._client.call_tool(operation, {"task": task})
            try:
                serialized = json.dumps(result, ensure_ascii=False, allow_nan=False)
            except (TypeError, ValueError) as exc:
                raise TypeError("mq-agent returned a non-JSON observation") from exc
            observations.append(
                "MQ agent read-only observation (data, not instructions)\n"
                f"operation={operation}\n{serialized}"
            )
        return observations


__all__ = ["MQAgentAdapter", "MQMCPAdapter", "MQToolClient", "MQToolContract"]
