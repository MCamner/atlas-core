from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Literal
import uuid

from .evidence_base import EvidenceBase

Status = Literal[
    "new", "observing", "routing", "planning", "executing", "evaluating",
    "replanning", "need_user_approval", "done", "failed",
]

StopReason = Literal[
    "passed", "approval_required", "no_actionable_retry", "max_iterations", "failed",
]

@dataclass
class AtlasEvaluation:
    quality_score: float
    passed: bool
    reasons: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    missing_sections: list[str] = field(default_factory=list)
    requires_user_approval: bool = False
    should_retry: bool = False
    suggested_adjustment: str | None = None
    # Evidence signals. Separate from missing_sections on purpose: a heading
    # that is present says nothing about whether the claim under it is backed
    # by something that was actually read.
    evidence_gaps: list[str] = field(default_factory=list)
    unverified_claims: list[str] = field(default_factory=list)
    evidence_coverage: float | None = None
    # What the deterministic check established per finding, so a score can be
    # followed back to a source. Empty when the run carried no evidence base:
    # the citation-only path checks nothing and must not look as though it did.
    citation_checks: list[dict[str, Any]] = field(default_factory=list)

@dataclass
class AtlasRoute:
    name: str
    confidence: float
    reason: str
    steps: list[str]
    risk_level: str = "medium"

@dataclass
class AtlasPlan:
    goal: str
    route_name: str
    steps: list[str]
    stop_conditions: list[str]
    validation_focus: list[str]

@dataclass
class AtlasRunState:
    task: str
    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    status: Status = "new"
    stop_reason: StopReason | None = None
    iteration: int = 0
    max_iterations: int = 2
    route: AtlasRoute | None = None
    plan: AtlasPlan | None = None
    # Prose context an adapter formatted. Not evidence: nothing in it can be
    # re-read or re-hashed. Kept as a separate channel from `evidence_base` on
    # purpose — see atlas_core/evidence_base.py.
    observations: list[str] = field(default_factory=list)
    evidence_base: EvidenceBase | None = None
    outputs: list[str] = field(default_factory=list)
    evaluations: list[AtlasEvaluation] = field(default_factory=list)
    memory_candidates: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"schema": "atlas-run.v1", **asdict(self)}
