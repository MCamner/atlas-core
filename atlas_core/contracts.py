"""Which documents Atlas Core emits, at which version, and who may write what.

Three questions this module answers, and one it refuses.

**What exists.** `CONTRACTS` names every document this package emits or accepts,
with the schema file that defines it. A document that is not in here has no
contract, which is a different statement from having a permissive one.

**Who may write each field.** `FIELD_OWNERS` is the rule this repository has
enforced case by case since P0.2, written down once. The producer supplies a
claim; the checker assigns a verdict; the host says what was read; the core owns
the run's identity and where it stopped. Scattered across modules that rule was
still true, but it could not be *read* — and a rule nobody can read is one a
future change breaks without noticing. Bound to the schema files by test.

**What may change without a new version.** `COMPATIBILITY` states it, and
`predecessor_of` says which contract each version succeeds so the rule can be
checked mechanically rather than remembered.

**What it refuses:** this module grants nothing. Naming `Approval.v1` does not
create a way to approve a write, and naming `Action.v1` does not make the loop
record actions. Both are contracts for information, and where the information
does not exist yet, the documents say `not_recorded` — see
`atlas_core.migrate`, and `docs/safety-model.md` on why an approval token is
harder than an approval field.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

#: Who is permitted to write a field. Not a description of who happens to — the
#: distinction matters, because the whole evidence model rests on a producer
#: being unable to write what only a checker may.
OWNERS: tuple[str, ...] = ("core", "host", "producer", "checker", "derived")

OWNER_MEANING: Mapping[str, str] = {
    # The loop itself: identity, where the run is, why it stopped. Nothing
    # outside the controller writes these, and nothing in a model's output can.
    "core": "the Atlas loop",
    # Trusted host code, outside Core. What was read, and what a person
    # approved. Never repository content, never model text — both are data.
    "host": "trusted host code",
    # Whatever answers: a model, a script, an operator. Everything here is a
    # claim until something else checks it.
    "producer": "whatever produced the answer",
    # The deterministic evidence layer. The only writer of a verdict, and the
    # reason a producer that sends one has its block refused rather than
    # stripped.
    "checker": "the deterministic evidence check",
    # Computed from other fields on the way out, never stored beside them. A
    # stored derived value is one that can contradict what it was derived from.
    "derived": "computed from other fields",
}


@dataclass(frozen=True)
class Contract:
    """One versioned document.

    `owners` maps a top-level field to who may write it. Fields absent from the
    map are not exempt — a test requires the map to cover every property the
    schema declares, so adding a field to a schema and forgetting to say who
    owns it fails rather than defaults to permissive.
    """

    name: str
    version: int
    schema_file: str
    #: The version this one succeeds, or `None` for a first version. What makes
    #: the compatibility rule checkable instead of aspirational.
    succeeds: str | None = None
    #: Fields the predecessor required that this version does not carry, each
    #: with the reason. Empty is the normal case; a non-empty entry is a
    #: deliberate, stated break and the only way a required field may vanish.
    dropped: Mapping[str, str] = field(default_factory=dict)
    owners: Mapping[str, str] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return f"{self.name}.v{self.version}"

    @property
    def schema_id(self) -> str:
        return f"atlas-{self.name.lower()}.v{self.version}.json"


#: What may change inside a version, and what forces a new one. Stated here
#: because it was once broken silently: `quality_score` changed from a weighted
#: score to a share of met criteria while keeping its name and its type, so a
#: consumer written against the old meaning kept parsing and kept being wrong.
#: `score_method` exists because of that, and this rule exists so it does not
#: need to happen twice.
COMPATIBILITY = """
Within a version, a schema MAY:
  - add an optional property
  - add an enum member to a field whose absent value is already meaningful
  - relax a description

Within a version, a schema MUST NOT:
  - add a required property
  - remove or rename any property
  - narrow a type, or remove an enum member
  - change what an existing field MEANS while keeping its name

The last one is the reason this rule is written down. The others are visible in
a diff; a changed meaning is not.
"""

CONTRACTS: dict[str, Contract] = {
    contract.id: contract
    for contract in (
        Contract(
            name="Observation",
            version=1,
            schema_file="atlas-observation.v1.json",
            owners={
                "schema": "core",
                "source_id": "derived",
                "source_type": "host",
                "path": "host",
                "collected_at": "host",
                "content_sha256": "host",
                "excerpt": "host",
                "line_start": "host",
                "line_end": "host",
                "snapshot_id": "host",
                "repo": "host",
                "ref": "host",
                "commit": "host",
                "worktree_state": "host",
                "confidentiality": "derived",
                "total_lines": "host",
                "read_in_full": "derived",
            },
        ),
        Contract(
            name="Finding",
            version=1,
            schema_file="atlas-finding.v1.json",
            owners={
                "schema": "core",
                "finding_id": "derived",
                "claim": "producer",
                "scope": "producer",
                # Assigned, not declared. What the producer said is kept beside
                # it in `declared_severity`, and survives as `severity` only on
                # a verified verdict.
                "severity": "checker",
                "severity_rationale": "producer",
                "declared_severity": "producer",
                "evidence": "producer",
                "verification_method": "checker",
                "verdict": "checker",
                "limitations": "producer",
                "reproducible_command": "producer",
            },
        ),
        Contract(
            name="Evaluation",
            version=2,
            schema_file="atlas-evaluation.v2.json",
            succeeds="Evaluation.v1",
            owners={
                "schema": "core",
                "evaluation_id": "derived",
                "run_id": "core",
                "iteration": "core",
                "quality_score": "checker",
                "score_method": "checker",
                "passed": "checker",
                "met_criteria": "checker",
                "unmet_criteria": "checker",
                "reasons": "checker",
                "missing": "checker",
                "missing_sections": "checker",
                "requires_user_approval": "core",
                "should_retry": "checker",
                "retry_is_possible": "checker",
                "suggested_adjustment": "checker",
                "next_action": "checker",
                "evidence_gaps": "checker",
                "unverified_claims": "checker",
                "evidence_coverage": "checker",
                "citation_checks": "checker",
                "blocked_by": "checker",
            },
        ),
        Contract(
            name="Action",
            version=1,
            schema_file="atlas-action.v1.json",
            owners={
                "schema": "core",
                "action_id": "derived",
                "run_id": "core",
                "iteration": "core",
                "kind": "core",
                "started_at": "core",
                "capability": "core",
                "target": "core",
                "input_sha256": "core",
                "outcome": "core",
                "error": "core",
            },
        ),
        Contract(
            name="Approval",
            version=1,
            schema_file="atlas-approval.v1.json",
            owners={
                "schema": "core",
                "approval_id": "derived",
                "run_id": "core",
                "iteration": "core",
                # Core decides an approval is *required*, from the task. A host
                # is the only thing that could ever grant one, which is why the
                # grant fields are the host's even though nothing writes them
                # yet.
                "required": "core",
                "reason": "core",
                "granted": "host",
                "granted_by": "host",
                "granted_at": "host",
                "binds_to": "host",
            },
        ),
        Contract(
            name="Event",
            version=1,
            schema_file="atlas-event.v1.json",
            owners={
                "schema": "core",
                "event_id": "derived",
                "run_id": "core",
                "sequence": "derived",
                "iteration": "core",
                "kind": "core",
                "recorded_at": "core",
                "call_id": "derived",
                "payload": "core",
            },
        ),
        Contract(
            name="Inspect",
            version=1,
            schema_file="atlas-inspect.v1.json",
            owners={
                "schema": "core",
                "run_id": "core",
                "status": "derived",
                "route": "derived",
                "iterations": "derived",
                "stop_reason": "derived",
                "stop_class": "derived",
                "sources": "derived",
                "source_details": "derived",
                "uncertainties": "derived",
                "unfinished_calls": "derived",
                "calls": "derived",
                "event_count": "derived",
                "started_at": "derived",
                "finished_at": "derived",
                "events": "core",
            },
        ),
        Contract(
            name="Status",
            version=1,
            schema_file="atlas-status.v1.json",
            owners={
                "schema": "core",
                "run_id": "core",
                "state": "derived",
                "status": "derived",
                "stop_reason": "derived",
                "iteration": "derived",
                "event_count": "derived",
                "last_event_kind": "derived",
                "cancel_requested": "derived",
            },
        ),
        Contract(
            name="Run",
            version=2,
            schema_file="atlas-run.v2.json",
            succeeds="Run.v1",
            owners={
                "schema": "core",
                "contracts": "core",
                "run_id": "core",
                "task": "core",
                "created_at": "core",
                "status": "core",
                "stop_reason": "core",
                "stop_class": "derived",
                "state_machine": "core",
                "iteration": "core",
                "max_iterations": "core",
                "route": "core",
                "plan": "core",
                "observations": "host",
                "evidence_manifest": "host",
                "outputs": "producer",
                "evaluations": "checker",
                "actions": "core",
                "approvals": "core",
                "memory_candidates": "core",
                "metadata": "core",
                "migration": "core",
            },
        ),
    )
}

#: The sub-contract versions a `Run.v2` document carries, so a consumer reads
#: the version rather than inferring it from the shape. Written into every such
#: document as `contracts`.
RUN_V2_CONTRACTS: Mapping[str, str] = {
    "observation": "atlas-observation.v1",
    "finding": "atlas-finding.v1",
    "evaluation": "atlas-evaluation.v2",
    "action": "atlas-action.v1",
    "approval": "atlas-approval.v1",
    "event": "atlas-event.v1",
    "route": "atlas-route.v1",
    "memory_candidate": "atlas-memory-candidate.v1",
}


def predecessor_of(contract_id: str) -> str | None:
    """The contract this one succeeds, or `None` if it is a first version."""
    return CONTRACTS[contract_id].succeeds


def owner_of(contract_id: str, field_name: str) -> str:
    """Who may write `field_name`. Raises for a field nobody declared an owner
    for, rather than returning a permissive default — an unowned field is a
    hole, and a hole that answers questions is worse than one that does not."""
    owners = CONTRACTS[contract_id].owners
    if field_name not in owners:
        raise KeyError(f"{contract_id} declares no owner for {field_name!r}")
    return owners[field_name]


__all__ = [
    "COMPATIBILITY",
    "CONTRACTS",
    "Contract",
    "OWNERS",
    "OWNER_MEANING",
    "RUN_V2_CONTRACTS",
    "owner_of",
    "predecessor_of",
]
