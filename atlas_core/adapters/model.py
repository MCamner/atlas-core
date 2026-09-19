from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

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
