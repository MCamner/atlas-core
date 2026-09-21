from __future__ import annotations

from dataclasses import dataclass, field, asdict, replace
from datetime import datetime, timezone
from typing import Any, Literal
import uuid

from .evidence_base import EvidenceBase
from .review_plan import ReviewPlan
from .redaction import redact_document
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
    "NEXT_ACTION_KINDS",
    "SCORE_METHODS",
    "CURRENT_SCORE_METHOD",
    "NextAction",
    "NextActionKind",
    "AtlasEvaluation",
    "AtlasRoute",
    "AtlasPlan",
    "AtlasRunState",
]

#: How `quality_score` was computed. A field name that keeps its spelling
#: while its meaning changes is a compatibility trap: a consumer written
#: against 1.0 reads the new number as the old one and never finds out. This
#: names the method, so the question is answerable without reading a changelog.
#:
#: `criteria_met_share` — the share of its route's exit criteria the answer
#: met. Reports; nothing compares it against a threshold.
#:
#: A document with **no** `score_method` predates P1.1 and carries the earlier
#: method: a weighted sum over output length and headings, multiplied by an
#: evidence factor, compared against 0.78. That method is gone, and it is named
#: here so an archived document can still be read correctly.
SCORE_METHODS: tuple[str, ...] = ("criteria_met_share", "weighted_sections_and_length")

CURRENT_SCORE_METHOD = "criteria_met_share"

NextActionKind = Literal[
    "observe_again",
    "answer_the_question",
    "repair_findings_block",
    "drop_refuted_claim",
    "restate_claim",
    "recite_from_source",
    "cite_sources",
    "add_sections",
]

#: The closed vocabulary, in the order an action is chosen from it. The order
#: is not severity: it is what has to happen **first** for the rest to be worth
#: doing. A block that cannot be parsed makes every question about an
#: individual citation moot, and a source that has moved cannot be re-cited at
#: all — so those come before anything about the text of a claim.
NEXT_ACTION_KINDS: tuple[str, ...] = (
    "observe_again",
    # After reading and before anything about the findings' quality: an answer
    # about the wrong subject cannot be repaired into an answer about the right
    # one, and polishing its citations would only make it read better.
    "answer_the_question",
    "repair_findings_block",
    "drop_refuted_claim",
    "restate_claim",
    "recite_from_source",
    "cite_sources",
    "add_sections",
)

#: Who can carry the action out. `observe_again` is the one a producer cannot
#: do: re-reading a source is the host's job, and a producer told to "try
#: harder" against a file that has moved would only invent something.
NEXT_ACTION_ACTORS: tuple[str, ...] = ("producer", "host")


@dataclass(frozen=True)
class NextAction:
    """What has to happen before the answer could be different, as data.

    The evaluator has always emitted gap *codes*; what to do about them lived
    in `suggested_adjustment` as English. A host or a model adapter that wanted
    to act on it had to parse prose to find out whether to re-cite, repair a
    block, or go and observe a source again — which is exactly what the API
    contract tells adapters not to do. This is that instruction as data. The
    prose stays beside it, for people.

    One action, not a list. Naming everything at once would leave the actor to
    decide what to do first, and the order in `NEXT_ACTION_KINDS` is precisely
    that decision. `gap_codes` still carries every outstanding gap, so nothing
    is hidden by choosing one.
    """

    kind: NextActionKind
    #: Every outstanding gap, not only the one this action addresses.
    gap_codes: list[str]
    actor: str = "producer"
    #: What the actor needs, per kind. Data, not a sentence.
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in NEXT_ACTION_KINDS:
            raise ValueError(
                f"kind must be one of {NEXT_ACTION_KINDS}, got {self.kind!r}"
            )
        if self.actor not in NEXT_ACTION_ACTORS:
            raise ValueError(
                f"actor must be one of {NEXT_ACTION_ACTORS}, got {self.actor!r}"
            )
        if not self.gap_codes:
            raise ValueError(
                "an action addresses at least one gap; an action with none is a "
                "next step nobody asked for"
            )


@dataclass
class AtlasEvaluation:
    # The share of its route's exit criteria this answer met. A report: nothing
    # branches on it. `passed` is decided by `unmet_criteria` being empty.
    quality_score: float
    passed: bool
    #: How `quality_score` was computed. See `SCORE_METHODS`.
    score_method: str = CURRENT_SCORE_METHOD
    # What the route declared it owed, and what it delivered. Named rather
    # than weighted: a requirement that can be outvoted by other requirements
    # is not one.
    met_criteria: list[str] = field(default_factory=list)
    unmet_criteria: list[str] = field(default_factory=list)
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
    # The same instruction as data. Prose is for a person; this is what a host
    # or an adapter branches on. None when nothing is outstanding.
    next_action: NextAction | None = None
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
    # What this run is actually looking into, for a route that reviews a
    # repository: the state, the question and the sources it needs. None for a
    # route with no review contract, which has a goal but not a question.
    review: ReviewPlan | None = None

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
        if reason == "budget_exhausted":
            # A quota may trip at any stage. This is a controlled interruption,
            # not a new general-purpose enter("done") transition.
            from .machine import TERMINAL_STATUSES, InvalidTransition
            if self.status in TERMINAL_STATUSES:
                raise InvalidTransition("a terminal run cannot stop again")
            self.status = spec.status
        else:
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

        The whole document is then masked. The evidence manifest was masked
        from the start, but it is not the only channel a source reaches: the
        prose `observations` list an adapter formats, and the output that
        repeats it back, used to leave verbatim — so a run whose manifest was
        clean could publish the same credential one key away. Masking the
        assembled document covers every channel at once, including ones added
        later, and `redaction.VERBATIM_KEYS` keeps the ids and digests that a
        reader follows back.
        """
        fields = asdict(replace(self, evidence_base=None))
        fields.pop("evidence_base", None)
        manifest = self.evidence_base.to_manifest() if self.evidence_base else None
        document = {
            "schema": "atlas-run.v1",
            **fields,
            # Which vocabulary the status and stop reason are drawn from, and
            # which kind of thing ended the run. `stop_class` is derived from
            # `stop_reason` rather than stored, so it cannot contradict it.
            "state_machine": STATE_MACHINE_VERSION,
            "stop_class": stop_class_of(self.stop_reason),
            "evidence_manifest": manifest,
        }
        redacted: dict[str, Any] = redact_document(document)
        return redacted
