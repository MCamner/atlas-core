"""Per-run, cooperative resource accounting for Atlas-managed work.

A synchronous Python callable cannot be interrupted by checking a clock. The
host/model adapter MUST honour ``deadline`` and invoke ``check`` at its nested
operations. Unknown usage is not converted into an invented token count.
These counters do not sandbox arbitrary Python inside an adapter.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from time import monotonic
from typing import Callable


class BudgetExceeded(RuntimeError):
    """A declared run limit has actually been reached."""


class UnmeteredUsage(RuntimeError):
    """An adapter did not report the usage needed to enforce the budget."""


@dataclass(frozen=True)
class RunLimits:
    wall_seconds: float
    model_calls: int
    tool_calls: int
    tokens: int
    output_bytes: int

    def __post_init__(self) -> None:
        if isinstance(self.wall_seconds, bool) or not isfinite(self.wall_seconds) or self.wall_seconds <= 0:
            raise ValueError("wall_seconds must be positive and finite")
        for field_name in ("model_calls", "tool_calls", "tokens", "output_bytes"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field_name} must be a nonnegative integer")


class RunBudget:
    """A single run's budget. Pass this same object through nested adapters.

    The deadline is monotonic and is checked before AND after synchronous
    calls; the adapter must enforce its own in-call timeout. ``tokens`` means
    the adapter's actual reported usage, not bytes or estimated tokens.
    """

    def __init__(self, limits: RunLimits, *, clock: Callable[[], float] = monotonic):
        self.limits = limits
        self._clock = clock
        self.deadline = clock() + limits.wall_seconds
        self.model_calls = 0
        self.tool_calls = 0
        self.tokens = 0
        self.output_bytes = 0

    def check(self) -> None:
        if self._clock() >= self.deadline:
            raise BudgetExceeded("wall_seconds")

    def reserve_model(self) -> None:
        self.check()
        if self.model_calls >= self.limits.model_calls:
            raise BudgetExceeded("model_calls")
        self.model_calls += 1

    def reserve_tool(self) -> None:
        self.check()
        if self.tool_calls >= self.limits.tool_calls:
            raise BudgetExceeded("tool_calls")
        self.tool_calls += 1

    def charge_tokens(self, usage: int | None) -> None:
        self.check()
        if isinstance(usage, bool) or not isinstance(usage, int) or usage < 0:
            raise UnmeteredUsage("model token usage missing or invalid")
        self.tokens += usage
        if self.tokens > self.limits.tokens:
            raise BudgetExceeded("tokens")

    def charge_output(self, output: str) -> None:
        self.check()
        self.output_bytes += len(output.encode("utf-8"))
        if self.output_bytes > self.limits.output_bytes:
            raise BudgetExceeded("output_bytes")

    def usage(self) -> dict[str, int | float]:
        return {"model_calls": self.model_calls, "tool_calls": self.tool_calls,
                "tokens": self.tokens, "output_bytes": self.output_bytes,
                "deadline_monotonic": self.deadline}
