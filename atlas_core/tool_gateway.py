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
from .eventlog import EventLog


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
    def __init__(
        self,
        *,
        budget: RunBudget,
        tools: Mapping[str, ToolDefinition],
        log: "EventLog | None" = None,
    ):
        if not isinstance(budget, RunBudget):
            raise TypeError("tool gateway requires a shared RunBudget")
        if any(name != tool.name for name, tool in tools.items()):
            raise ValueError("tool registry key/name mismatch")
        self.budget = budget
        self._tools = dict(tools)
        #: The run's append-only log, or None. This is where `denied` is
        #: knowable: a refusal happens here, before any handler runs, and
        #: nothing downstream can tell a denial from a call that was never
        #: attempted. Optional and inert — a gateway with no log denies and
        #: allows exactly what it did before.
        self._log = log

    def invoke(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        self.budget.check()
        # Started before anything can refuse it, so a denial is recorded as a
        # call that happened and was refused — not as one that never occurred.
        # A reader of the log needs to see the attempt.
        call = (
            self._log.start_call("tool_call", target=name, call_input=arguments)
            if self._log is not None
            else None
        )

        def record(outcome: str, error: str | None = None) -> None:
            """Every exit from here names an outcome.

            An unfinished call means "began, outcome unknown", which is a real
            state and an expensive one — it is what a crash leaves, and what the
            resume work has to reason about. Leaving one behind for a refusal
            this code saw and understood would put noise in exactly the signal
            that has to stay trustworthy.
            """
            if self._log is not None and call is not None:
                self._log.finish_call(call, outcome, error=error)

        # Name lookup precedes budget reservation. An attacker cannot use
        # arbitrary model/README text to invent a new tool.
        tool = self._tools.get(name)
        if tool is None:
            record("denied", "tool not registered")
            raise ToolDenied("tool not registered")
        if tool.capability != "read":
            # No write/approval execution exists in P0.3. A string saying
            # "approved" or a declared read-only operation cannot bypass it.
            record("denied", "capability not allowed in read-only run")
            raise ToolDenied("capability not allowed in read-only run")
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict) or not all(isinstance(k, str) for k in arguments):
            record("denied", "TypeError")
            raise TypeError("tool arguments must be a string-keyed object")

        try:
            # A quota refusal here is a denial, not a failure: nothing ran.
            self.budget.reserve_tool()
        except Exception as exc:
            record("denied", type(exc).__name__)
            raise

        try:
            result = tool.handler(ToolContext(self), dict(arguments))
            self.budget.check()
            # Do not return an unlimited tool result. Strict JSON also disallows
            # arbitrary objects with surprising __str__/serialization behaviour.
            try:
                serialized = json.dumps(result, ensure_ascii=False, allow_nan=False)
            except (ValueError, TypeError) as exc:
                raise TypeError("tool returned non-JSON value") from exc
            self.budget.charge_output(serialized)
        except Exception as exc:
            # The handler ran, so the side effect may have happened. `failed`
            # rather than `denied`, and never left unfinished.
            record("failed", type(exc).__name__)
            raise
        record("ok")
        return result
