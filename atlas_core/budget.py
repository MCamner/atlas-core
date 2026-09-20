"""Per-run, cooperative resource accounting for Atlas-managed work.

The monotonic deadline and cancellation are checked at each boundary. A
synchronous Python handler cannot be preempted: adapters must impose their
own I/O timeout and use the shared budget for nested calls. This is not an
OS sandbox, a claim of hard process termination, or a token estimate.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from threading import RLock
from time import monotonic
from typing import Callable


class BudgetExceeded(RuntimeError):
    """A declared run limit has actually been reached."""


class RunCancelled(RuntimeError):
    """The caller requested cancellation before the next operation."""


class UnmeteredUsage(RuntimeError):
    """An adapter did not report usage needed to enforce the budget."""


@dataclass(frozen=True)
class RunLimits:
    wall_seconds: float
    model_calls: int
    tool_calls: int
    tokens: int
    output_bytes: int

    def __post_init__(self) -> None:
        if (isinstance(self.wall_seconds, bool) or not isinstance(self.wall_seconds, (int, float))
                or not isfinite(self.wall_seconds) or self.wall_seconds <= 0):
            raise ValueError("wall_seconds must be positive and finite")
        for field_name in ("model_calls", "tool_calls", "tokens", "output_bytes"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field_name} must be a nonnegative integer")


class RunBudget:
    """One budget shared by retries, adapters and nested gateway invocations."""

    def __init__(
        self,
        limits: RunLimits,
        *,
        clock: Callable[[], float] = monotonic,
        cancelled: Callable[[], bool] | None = None,
    ):
        self.limits = limits
        self._clock = clock
        self._cancelled = cancelled
        self._lock = RLock()
        self.deadline = clock() + limits.wall_seconds
        self.model_calls = 0
        self.tool_calls = 0
        self.tokens = 0
        self.output_bytes = 0

    def check(self) -> None:
        if self._cancelled is not None and self._cancelled():
            raise RunCancelled("cancelled")
        if self._clock() >= self.deadline:
            raise BudgetExceeded("wall_seconds")

    def reserve_model(self) -> None:
        with self._lock:
            self.check()
            if self.model_calls >= self.limits.model_calls:
                raise BudgetExceeded("model_calls")
            self.model_calls += 1

    def reserve_tool(self) -> None:
        with self._lock:
            self.check()
            if self.tool_calls >= self.limits.tool_calls:
                raise BudgetExceeded("tool_calls")
            self.tool_calls += 1

    def charge_tokens(self, usage: int | None) -> None:
        with self._lock:
            self.check()
            if isinstance(usage, bool) or not isinstance(usage, int) or usage < 0:
                raise UnmeteredUsage("model token usage missing or invalid")
            self.tokens += usage
            if self.tokens > self.limits.tokens:
                raise BudgetExceeded("tokens")

    def charge_output(self, output: str) -> None:
        with self._lock:
            self.check()
            self.output_bytes += len(output.encode("utf-8"))
            if self.output_bytes > self.limits.output_bytes:
                raise BudgetExceeded("output_bytes")

    def usage(self) -> dict[str, int | float]:
        with self._lock:
            return {
                "model_calls": self.model_calls,
                "tool_calls": self.tool_calls,
                "tokens": self.tokens,
                "output_bytes": self.output_bytes,
                "deadline_monotonic": self.deadline,
            }
