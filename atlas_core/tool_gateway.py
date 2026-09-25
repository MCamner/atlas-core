"""Atlas-owned, fail-closed boundary for trusted host tool adapters.

Repository and model text are data: only host code registers definitions. The
gateway enforces route, capability, JSON schemas, timeout, shared budget and
retry policy before returning a result. ``isolated_process`` supplies a hard
POSIX process timeout; it is process isolation, not an OS privilege sandbox.

``invoke`` runs ``read`` tools only. A ``write`` tool runs through
``invoke_write`` alone, which host code calls with an approval token for the
exact operation; the model's path (``invoke``, ``ToolContext.invoke``) never
reaches it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import multiprocessing
from multiprocessing.connection import Connection
import os
import re
import signal
import time
from typing import Any, Callable, Mapping

from .approval import ApprovalAuthority, Operation, thaw
from .budget import RunBudget
from .eventlog import EventLog


class ToolDenied(PermissionError):
    """A request was denied before any handler was invoked."""


class ToolSchemaError(ValueError):
    """Tool input or output did not match its host-declared JSON schema."""


class ToolTimeout(TimeoutError):
    """A tool exceeded its own timeout or the remaining run deadline."""


class _RemoteToolError(RuntimeError):
    def __init__(self, error: str, retryable: bool) -> None:
        super().__init__(error)
        self.retryable = retryable


JsonSchema = Mapping[str, Any]


def _validate_schema(value: Any, schema: JsonSchema, *, path: str = "$") -> None:
    """Validate the bounded JSON-schema subset tool contracts use."""
    expected = schema.get("type")
    matches = {
        "object": lambda item: isinstance(item, dict),
        "array": lambda item: isinstance(item, list),
        "string": lambda item: isinstance(item, str),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "number": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
        "boolean": lambda item: isinstance(item, bool),
        "null": lambda item: item is None,
    }
    if expected is not None:
        allowed = [expected] if isinstance(expected, str) else list(expected)
        if not allowed or any(item not in matches for item in allowed):
            raise ValueError(f"unsupported schema type at {path}")
        if not any(matches[item](value) for item in allowed):
            raise ToolSchemaError(f"{path} must have type {allowed}")
    if "enum" in schema and value not in schema["enum"]:
        raise ToolSchemaError(f"{path} is not in the declared enum")
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        if not isinstance(properties, Mapping) or not isinstance(required, list):
            raise ValueError(f"invalid object schema at {path}")
        missing = [name for name in required if name not in value]
        if missing:
            raise ToolSchemaError(f"{path} is missing required keys: {missing}")
        if schema.get("additionalProperties") is False:
            extra = sorted(set(value) - set(properties))
            if extra:
                raise ToolSchemaError(f"{path} has undeclared keys: {extra}")
        for name, item in value.items():
            child = properties.get(name)
            if isinstance(child, Mapping):
                _validate_schema(item, child, path=f"{path}.{name}")
    if isinstance(value, list) and isinstance(schema.get("items"), Mapping):
        for index, item in enumerate(value):
            _validate_schema(item, schema["items"], path=f"{path}[{index}]")


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    capability: str
    handler: Callable[["ToolContext", dict[str, Any]], Any]
    allowed_routes: tuple[str, ...] = ("*",)
    input_schema: JsonSchema = field(default_factory=lambda: {"type": "object"})
    output_schema: JsonSchema = field(default_factory=dict)
    timeout_seconds: float = 5.0
    sandbox: str = "in_process"
    idempotent: bool | None = None
    max_attempts: int = 1
    retry_on: tuple[type[Exception], ...] = (OSError, TimeoutError)
    #: For a ``write`` tool: the exact operation these arguments perform, built
    #: by host code (repository, ref and the commit it applies to). What a
    #: person approves is this, never the model's description of it.
    describe: Callable[[dict[str, Any]], Operation] | None = None

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_]*", self.name):
            raise ValueError("tool name must be lowercase and literal")
        if self.capability not in {"read", "write", "network"}:
            raise ValueError("unknown tool capability")
        if not callable(self.handler):
            raise TypeError("tool handler must be callable")
        if not self.allowed_routes or any(
            not isinstance(route, str) or not route for route in self.allowed_routes
        ):
            raise ValueError("allowed_routes must declare at least one route")
        if self.sandbox not in {"in_process", "isolated_process"}:
            raise ValueError("sandbox must be in_process or isolated_process")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or self.timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be positive")
        if isinstance(self.max_attempts, bool) or self.max_attempts < 1:
            raise ValueError("max_attempts must be a positive integer")
        if self.max_attempts > 1 and self.idempotent is not True:
            raise ValueError("retries require idempotent=True")
        if self.capability == "write" and self.max_attempts != 1:
            raise ValueError("a write runs once per approval; it is never retried")
        if any(
            not isinstance(item, type) or not issubclass(item, Exception)
            for item in self.retry_on
        ):
            raise TypeError("retry_on must contain Exception types")
        for schema in (self.input_schema, self.output_schema):
            if not isinstance(schema, Mapping):
                raise TypeError("tool schemas must be mappings")

    @property
    def is_idempotent(self) -> bool:
        return self.idempotent is True or (
            self.idempotent is None and self.capability == "read"
        )


@dataclass(frozen=True)
class ToolContext:
    gateway: "ToolGateway"
    nested_allowed: bool = True

    @property
    def budget(self) -> RunBudget:
        return self.gateway.budget

    def invoke(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        if not self.nested_allowed:
            raise ToolDenied("nested calls are unavailable in isolated_process")
        return self.gateway.invoke(name, arguments)


def _isolated_worker(
    channel: Connection,
    handler: Callable[[ToolContext, dict[str, Any]], Any],
    gateway: "ToolGateway",
    arguments: dict[str, Any],
    retry_on: tuple[type[Exception], ...],
) -> None:
    os.setsid()
    try:
        result = handler(ToolContext(gateway, nested_allowed=False), arguments)
        payload = {"ok": True, "result": result}
        raw = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except BaseException as exc:
        raw = json.dumps(
            {
                "ok": False,
                "error": type(exc).__name__,
                "message": str(exc)[:256],
                "retryable": isinstance(exc, retry_on),
            },
            ensure_ascii=False,
        ).encode("utf-8")
    try:
        channel.send_bytes(raw)
    except (OSError, ValueError):
        pass
    finally:
        channel.close()


class ToolGateway:
    def __init__(
        self,
        *,
        budget: RunBudget,
        tools: Mapping[str, ToolDefinition],
        log: EventLog | None = None,
        approvals: ApprovalAuthority | None = None,
    ):
        if not isinstance(budget, RunBudget):
            raise TypeError("tool gateway requires a shared RunBudget")
        if any(name != tool.name for name, tool in tools.items()):
            raise ValueError("tool registry key/name mismatch")
        self.budget = budget
        self._tools = dict(tools)
        self._log = log
        self._approvals = approvals
        self._route: str | None = None

    def set_route(self, route: str) -> None:
        if not route:
            raise ValueError("route cannot be empty")
        self._route = route

    def _start_call(
        self,
        tool: ToolDefinition | None,
        name: str,
        arguments: object,
        attempt: int,
    ) -> str | None:
        if self._log is None:
            return None
        return self._log.start_call(
            "tool_call",
            target=name,
            call_input=arguments,
            idempotent=tool.is_idempotent if tool is not None else False,
            capability=tool.capability if tool is not None else None,
            route=self._route,
            sandbox=tool.sandbox if tool is not None else None,
            attempt=attempt,
        )

    def _finish(
        self, call: str | None, outcome: str, error: str | None = None
    ) -> None:
        if self._log is not None and call is not None:
            self._log.finish_call(call, outcome, error=error)

    def _run_isolated(self, tool: ToolDefinition, arguments: dict[str, Any]) -> Any:
        if os.name != "posix":
            raise ToolDenied("isolated_process requires POSIX")
        context = multiprocessing.get_context("fork")
        receive, send = context.Pipe(duplex=False)
        process = context.Process(
            target=_isolated_worker,
            args=(send, tool.handler, self, arguments, tool.retry_on),
            daemon=False,
        )
        timeout = min(tool.timeout_seconds, self.budget.remaining_seconds())
        try:
            process.start()
            send.close()
            if not receive.poll(timeout):
                raise ToolTimeout(f"{tool.name} exceeded {timeout:.3f}s")
            raw = receive.recv_bytes(maxlength=16 * 1024 * 1024)
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict) or payload.get("ok") is not True:
                error = (
                    payload.get("error", "ToolProcessError")
                    if isinstance(payload, dict)
                    else "ToolProcessError"
                )
                raise _RemoteToolError(
                    str(error), bool(payload.get("retryable", False))
                )
            return payload.get("result")
        finally:
            if process.pid is not None and process.is_alive():
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
                process.kill()
            process.join(timeout=1)
            receive.close()
            send.close()

    def _execute(self, tool: ToolDefinition, arguments: dict[str, Any]) -> Any:
        if tool.sandbox == "isolated_process":
            return self._run_isolated(tool, arguments)
        started = time.monotonic()
        result = tool.handler(ToolContext(self), dict(arguments))
        if time.monotonic() - started > tool.timeout_seconds:
            raise ToolTimeout(f"{tool.name} exceeded {tool.timeout_seconds:.3f}s")
        return result

    def invoke(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        self.budget.check()
        tool = self._tools.get(name)
        call = self._start_call(tool, name, arguments, 1)
        if tool is None:
            self._finish(call, "denied", "tool not registered")
            raise ToolDenied("tool not registered")
        if tool.capability != "read":
            self._finish(call, "denied", "capability not allowed in read-only run")
            raise ToolDenied("capability not allowed in read-only run")
        if "*" not in tool.allowed_routes and self._route not in tool.allowed_routes:
            self._finish(call, "denied", "tool not allowed for route")
            raise ToolDenied("tool not allowed for route")
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict) or not all(
            isinstance(key, str) for key in arguments
        ):
            self._finish(call, "denied", "TypeError")
            raise TypeError("tool arguments must be a string-keyed object")
        try:
            _validate_schema(arguments, tool.input_schema)
        except ToolSchemaError as exc:
            self._finish(call, "denied", "ToolSchemaError")
            raise ToolSchemaError("tool input does not match input_schema") from exc

        for attempt in range(1, tool.max_attempts + 1):
            if attempt > 1:
                call = self._start_call(tool, name, arguments, attempt)
            try:
                self.budget.reserve_tool()
            except Exception as exc:
                self._finish(call, "denied", type(exc).__name__)
                raise
            try:
                result = self._execute(tool, arguments)
                self.budget.check()
                serialized = json.dumps(result, ensure_ascii=False, allow_nan=False)
                _validate_schema(result, tool.output_schema)
                self.budget.charge_output(serialized)
            except Exception as exc:
                self._finish(call, "failed", type(exc).__name__)
                retryable = isinstance(exc, tool.retry_on) or (
                    isinstance(exc, _RemoteToolError) and exc.retryable
                )
                if attempt < tool.max_attempts and retryable:
                    continue
                if isinstance(exc, ToolSchemaError):
                    raise ToolSchemaError(
                        "tool output does not match output_schema"
                    ) from exc
                if isinstance(exc, (ValueError, TypeError)) and "JSON" in str(exc):
                    raise TypeError("tool returned non-JSON value") from exc
                raise
            self._finish(call, "ok")
            return result
        raise AssertionError("positive max_attempts guarantees an attempt")

    def invoke_write(
        self, name: str, arguments: dict[str, Any], *, token: str, iteration: int = 0
    ) -> Any:
        """Run one ``write`` tool, once, if ``token`` approves exactly this call.

        Every check that can refuse runs before the handler: registration,
        capability, route, input schema, the tool's own description of the
        operation, and the approval (validity, expiry, single use, operation
        digest, repository state). A refusal leaves nothing changed.
        """
        self.budget.check()
        tool = self._tools.get(name)
        call = self._start_call(tool, name, arguments, 1)

        def deny(reason: str) -> None:
            self._finish(call, "denied", reason)

        if tool is None:
            deny("tool not registered")
            raise ToolDenied("tool not registered")
        if tool.capability != "write" or tool.describe is None:
            deny("not a described write tool")
            raise ToolDenied("not a described write tool")
        if self._approvals is None:
            deny("no approval authority")
            raise ToolDenied("no approval authority")
        if "*" not in tool.allowed_routes and self._route not in tool.allowed_routes:
            deny("tool not allowed for route")
            raise ToolDenied("tool not allowed for route")
        if not isinstance(arguments, dict) or not all(isinstance(k, str) for k in arguments):
            deny("TypeError")
            raise TypeError("tool arguments must be a string-keyed object")
        # One copy, taken now, is what gets described, approved and run. The
        # caller's objects can change after this without changing the write.
        try:
            arguments = json.loads(json.dumps(arguments, allow_nan=False))
        except (TypeError, ValueError) as exc:
            deny("TypeError")
            raise TypeError("write arguments must be JSON") from exc
        try:
            _validate_schema(arguments, tool.input_schema)
        except ToolSchemaError as exc:
            deny("ToolSchemaError")
            raise ToolSchemaError("tool input does not match input_schema") from exc
        try:
            operation = tool.describe(thaw(arguments))
            if operation.tool != name:
                raise ValueError("operation names another tool")
            self._approvals.consume(token, operation, iteration=iteration)
        except Exception as exc:
            deny(type(exc).__name__)
            raise
        try:
            self.budget.reserve_tool()
        except Exception as exc:
            deny(type(exc).__name__)
            raise
        try:
            result = self._execute(tool, thaw(arguments))
            self.budget.check()
            serialized = json.dumps(result, ensure_ascii=False, allow_nan=False)
            _validate_schema(result, tool.output_schema)
            self.budget.charge_output(serialized)
        except Exception as exc:
            # The write may have happened. `failed` says the call did not
            # report success, not that nothing changed.
            self._finish(call, "failed", type(exc).__name__)
            raise
        self._finish(call, "ok")
        return result


__all__ = [
    "ToolContext",
    "ToolDefinition",
    "ToolDenied",
    "ToolGateway",
    "ToolSchemaError",
    "ToolTimeout",
]
