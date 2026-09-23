from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from atlas_core.state import AtlasEvaluation, AtlasPlan, AtlasRoute


@dataclass
class ModelResult:
    """Provider-neutral result from a live model adapter."""

    output: str
    model: str | None = None
    provider: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)


class ModelAdapter(Protocol):
    """Contract for pluggable live model execution.

    Implementations may call any provider, but they must return plain Atlas
    output text plus provider-neutral metadata. Write-like tool use stays out
    of this contract and must be gated by the controller safety checks.
    """

    def execute(
        self,
        *,
        task: str,
        route: AtlasRoute,
        plan: AtlasPlan,
        observations: list[str],
        feedback: AtlasEvaluation | None = None,
    ) -> ModelResult:
        ...


class StubModelAdapter:
    """A deterministic stand-in for a provider, for tests and CI.

    Shipped rather than redefined per test file so the model path has one
    reference implementation. It records the keyword arguments it was called
    with, which is what makes "the controller passed the previous evaluation
    back in" assertable.
    """

    idempotent = True

    def __init__(
        self,
        output: str,
        *,
        provider: str = "stub",
        model: str = "stub-model",
        metadata: dict[str, str] | None = None,
    ):
        self.output = output
        self.provider = provider
        self.model = model
        self.metadata = metadata or {}
        # Any, not object: callers assert on route.name and plan.steps.
        self.calls: list[dict[str, Any]] = []

    def execute(self, **kwargs: Any) -> ModelResult:
        self.calls.append(kwargs)
        return ModelResult(
            output=self.output,
            provider=self.provider,
            model=self.model,
            metadata=dict(self.metadata),
        )
