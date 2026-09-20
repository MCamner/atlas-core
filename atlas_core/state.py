from __future__ import annotations

from dataclasses import dataclass, field, asdict, replace
from datetime import datetime, timezone
from typing import Any
import uuid

from .evidence_base import EvidenceBase
from .machine import (
    STATE_MACHINE_VERSION,
    Status,
    StopReason,
    check_transition,
    spec_for,
    stop_class_of,
)

__all__ = [
    "Status",
    "StopReason",
    "AtlasEvaluation",
    "AtlasRoute",
    "AtlasPlan",
    "AtlasRunState",
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
    # Whether anything remains that another pass could act on, ignoring the
    # iteration budget. `should_retry` folds the budget in, so the two together
    # say whether the bound is what stopped the run or whether there was
    # nothing left to try — which are different stop reasons.
    retry_is_possible: bool = False
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
    # Evidence failures no re-wording can repair, as status codes. The
    # controller needs this to tell "the answer was not established" from "a
    # source moved under the run"; reading it out of the prose in `missing`
    # would make a stop reason depend on how a sentence is worded.
    blocked_by: list[str] = field(default_factory=list)

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
    # Raw: holds excerpts and the absolute root. Never serialised as-is —
    # `to_dict` exports `evidence_manifest` instead. See evidence_base.py.
    evidence_base: EvidenceBase | None = None
    outputs: list[str] = field(default_factory=list)
    evaluations: list[AtlasEvaluation] = field(default_factory=list)
    memory_candidates: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def enter(self, status: Status) -> None:
        """Move to `status`, refusing a move the state machine does not allow.

        Raising is the point. An illegal transition means the controller has
        lost track of where the run is, and the stop reason it reports next
        would be wrong in a way nothing downstream could detect.
        """
        check_transition(self.status, status)
        self.status = status

    def stop(self, reason: StopReason) -> None:
        """End the run for `reason`, taking the terminal status from it.

        Status and stop reason are set together, from one table, so a run can
        never report a runtime failure while claiming it is done.
        """
        spec = spec_for(reason)
        self.enter(spec.status)
        self.stop_reason = reason

    def to_dict(self) -> dict[str, Any]:
        """Render the run as an `atlas-run.v1` document.

        `evidence_base` is deliberately not in the output. `asdict` would walk
        straight into it and publish every excerpt the run read plus the
        absolute path it read from; the export is a sanitised manifest instead.

        It is cleared *before* `asdict` runs, not filtered out afterwards.
        `asdict` deep-copies as it walks, and the base holds source readers a
        host supplied — one wrapping a network client cannot be copied at all,
        so filtering after the walk would raise while rendering a run.
        """
        fields = asdict(replace(self, evidence_base=None))
        fields.pop("evidence_base", None)
        manifest = self.evidence_base.to_manifest() if self.evidence_base else None
        return {
            "schema": "atlas-run.v1",
            **fields,
            # Which vocabulary the status and stop reason are drawn from, and
            # which kind of thing ended the run. `stop_class` is derived from
            # `stop_reason` rather than stored, so it cannot contradict it.
            "state_machine": STATE_MACHINE_VERSION,
            "stop_class": stop_class_of(self.stop_reason),
            "evidence_manifest": manifest,
        }
