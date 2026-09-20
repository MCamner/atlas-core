"""Atlas-owned tool execution boundary.

Only trusted host code may register ToolDefinition handlers. Repository/model text
is always data and cannot register tools, authorize writes or pick capabilities.
A handler is Python code in the host process, NOT a sandbox: all privileged
adapters must be reviewed and must not call external tools around this gateway.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any, Callable, Mapping

from .budget import RunBudget


class ToolDenied(PermissionError):
    """A request was denied before any handler was invoked."""


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    capability: str
    handler: Callable[["ToolContext", dict[str, Any]], Any]

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_]*", self.name):
            raise ValueError("tool name must be lowercase and literal")
        if self.capability not in {"read", "write", "network"}:
            raise ValueError("unknown tool capability")
        if not callable(self.handler):
            raise TypeError("tool handler must be callable")


@dataclass(frozen=True)
class ToolContext:
    """Nested tool requests carry the SAME gateway and budget, never a reset."""
    gateway: "ToolGateway"

    @property
    def budget(self) -> RunBudget:
        return self.gateway.budget

    def invoke(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        return self.gateway.invoke(name, arguments)


class ToolGateway:
    def __init__(self, *, budget: RunBudget, tools: Mapping[str, ToolDefinition]):
        if not isinstance(budget, RunBudget):
            raise TypeError("tool gateway requires a shared RunBudget")
        if any(name != tool.name for name, tool in tools.items()):
            raise ValueError("tool registry key/name mismatch")
        self.budget = budget
        self._tools = dict(tools)

    def invoke(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        self.budget.check()
        # Name lookup precedes budget reservation. An attacker cannot use
        # arbitrary model/README text to invent a new tool.
        tool = self._tools.get(name)
        if tool is None:
            raise ToolDenied("tool not registered")
        if tool.capability != "read":
            # No write/approval execution exists in P0.3. A string saying
            # "approved" or a declared read-only operation cannot bypass it.
            raise ToolDenied("capability not allowed in read-only run")
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict) or not all(isinstance(k, str) for k in arguments):
            raise TypeError("tool arguments must be a string-keyed object")
        self.budget.reserve_tool()
        result = tool.handler(ToolContext(self), dict(arguments))
        self.budget.check()
        # Do not return an unlimited tool result. Strict JSON also disallows
        # arbitrary objects with surprising __str__/serialization behaviour.
        try:
            serialized = json.dumps(result, ensure_ascii=False, allow_nan=False)
        except (ValueError, TypeError) as exc:
            raise TypeError("tool returned non-JSON value") from exc
        self.budget.charge_output(serialized)
        return result
