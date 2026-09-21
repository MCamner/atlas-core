"""P0.2b: deciding whether the source supports the claim.

ROADMAP.md P0.2. Citation integrity established that a pointer holds and said
nothing about the claim. This module settles claims — but only claims stated in
a form where settling them means something.

## The gap this module is shaped by

An earlier version let a finding pair free text with a separately chosen
predicate, and granted a strong verdict when the predicate was settled. The
predicate was deterministic; its *relevance* to the claim was not checked, and
that broke both directions:

    1. FALSKT pastaende, latt orelaterat villkor:
       passed=True  verdict=verified
    2. SANT pastaende, orelaterat villkor som motbevisas:
       passed=False verdict=contradicted

A false claim earned `verified` because `# Atlas Core` happens to be in the
README, and a true one earned `contradicted` for the same reason. Deciding a
producer-chosen predicate is not deciding the producer's claim.

## A typed claim closes the gap by construction

The only route to `verified` or `contradicted` is a **typed claim**, where the
claim *is* the predicate. A producer does not supply a sentence and a separate
test of it; it supplies `source_contains_literal` or `source_lacks_literal`
over a cited source, and the human-readable text is **derived** from that. The
producer's own `claim` string must equal the derivation, so the sentence a
reader sees cannot say more than what was settled.

Free text keeps `insufficient_evidence`. Not because free-text claims are
worthless, but because nothing here can check that a predicate is a fair test
of a sentence. Doing that needs entailment, which is not a deterministic
problem, and guessing at it is what this phase removes.

## A free condition stays, as a diagnostic

`claim_check` survives for free-text findings and produces
`condition_supported` or `condition_refuted`. Neither is a verdict and neither
can reach `PASS`. The naming is the point: a producer's own test passing says
its test passed.

## Scope is the observed range, not the file

A typed claim is settled against the lines the observation actually recorded.
`collect_observation` keeps a bounded excerpt, so searching the whole file
would let text nobody observed decide a verdict — the same defect
`quote_outside_excerpt` refuses on the citation side. The derived claim text
names the range, so a reader sees what was searched.

## Literal text only

A producer-supplied regular expression is untrusted input, and a crafted one
can hang the checker. A literal search cannot.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from .finding import Finding, SourceReader, resolve_readers, severity_after
from .integrity import PathRefused
from .observation import Observation
from .snapshot import sha256_text


class ClaimKind(str, Enum):
    """The forms of claim this checker can settle.

    Closed on purpose. Each names its own text, source and scope, so there is
    no room between what was claimed and what was tested.
    """

    CONTAINS = "source_contains_literal"
    LACKS = "source_lacks_literal"


class ConditionKind(str, Enum):
    """A free-standing test a producer declares about a free-text finding."""

    ABSENT = "absent"
    PRESENT = "present"


CLAIM_KINDS: frozenset[str] = frozenset(kind.value for kind in ClaimKind)
SUPPORTED_KINDS: frozenset[str] = frozenset(kind.value for kind in ConditionKind)


class ClaimResult(str, Enum):
    """What was settled, and — by its name — how much that is worth."""

    #: Reachable only from a typed claim. The claim itself held.
    VERIFIED = "verified"
    #: Reachable only from a typed claim. The source refutes the claim itself.
    CONTRADICTED = "contradicted"
    #: A free condition passed. Says the producer's own test passed, no more.
    CONDITION_SUPPORTED = "condition_supported"
    #: A free condition failed. Says the producer's own test failed, no more.
    CONDITION_REFUTED = "condition_refuted"
    #: Free text with no declared test at all.
    NOT_DECLARED = "not_declared"
    #: The finding's prose says something other than what its typed claim says.
    CLAIM_TEXT_MISMATCH = "claim_text_mismatch"
    #: Declared in a form this checker cannot settle.
    UNSUPPORTED_KIND = "unsupported_kind"
    #: About a source the finding does not cite.
    SOURCE_NOT_CITED = "source_not_cited"
    #: Unreadable, moved, or no longer what was observed.
    SOURCE_UNAVAILABLE = "source_unavailable"


#: The only results that may move a finding's verdict off
#: `insufficient_evidence`. Everything else is a record, not a decision.
DECISIVE: frozenset[ClaimResult] = frozenset(
    {ClaimResult.VERIFIED, ClaimResult.CONTRADICTED}
)


@dataclass(frozen=True)
class TypedClaim:
    """A claim stated so that settling it settles the claim.

    Text, source and scope are one object rather than three independently
    chosen ones, which is what makes the predicate's relevance structural
    instead of asserted.
    """

    kind: ClaimKind
    source_id: str
    text: str

    def __post_init__(self) -> None:
        if not self.text:
            raise ValueError(
                "a claim must name text to look for; an empty string matches "
                "everything and would settle nothing"
            )
        if not self.source_id:
            raise ValueError("a claim must name the source it is about")

    def render(self, path: str, line_start: int, line_end: int) -> str:
        """The sentence this claim means, for a human to read.

        Derived rather than accepted from the producer, and it names the range
        it was settled over — a claim about lines 1-5 must not read as a claim
        about the file.
        """
        quoted = json.dumps(self.text, ensure_ascii=False)
        verb = "contain" if self.kind is ClaimKind.CONTAINS else "do not contain"
        return f"{path} lines {line_start}-{line_end} {verb} {quoted}"

    def holds_for(self, observed: str) -> bool:
        if self.kind is ClaimKind.CONTAINS:
            return self.text in observed
        return self.text not in observed


@dataclass(frozen=True)
class ClaimCondition:
    """A free-standing test a producer declares about a free-text claim.

    Deciding it decides the test, not the claim. `check_condition` never
    returns a decisive result, and the names it does return say so.
    """

    kind: ConditionKind
    source_id: str
    text: str

    def __post_init__(self) -> None:
        if not self.text:
            raise ValueError(
                "a condition must name text to look for; an empty string matches "
                "everything and would settle nothing"
            )
        if not self.source_id:
            raise ValueError("a condition must name the source it is about")

    def holds_for(self, observed: str) -> bool:
        if self.kind is ConditionKind.ABSENT:
            return self.text not in observed
        return self.text in observed


@dataclass(frozen=True)
class ClaimVerdict:
    """The outcome of checking a claim, and what it is worth."""

    result: ClaimResult
    reason: str
    #: What was evaluated, so a reader can see the scope it was settled over.
    checked: dict[str, Any] | None = None

    def is_decisive(self) -> bool:
        """Whether this may move the finding's verdict.

        Only a typed claim gets here. A settled condition does not, however
        cleanly it was settled.
        """
        return self.result in DECISIVE

    def to_dict(self) -> dict[str, Any]:
        return {
            "result": self.result.value,
            "reason": self.reason,
            "checked": self.checked,
            "is_decisive": self.is_decisive(),
        }


def build_typed_claim(payload: object) -> TypedClaim | None:
    """Read a typed claim, refusing one this checker cannot settle."""
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise TypeError(f"typed_claim must be an object, got {type(payload).__name__}")
    kind = str(payload.get("kind", ""))
    if kind not in CLAIM_KINDS:
        raise ValueError(
            f"typed_claim kind must be one of {sorted(CLAIM_KINDS)}, got {kind!r}"
        )
    return TypedClaim(
        kind=ClaimKind(kind),
        source_id=str(payload["source_id"]),
        text=str(payload["text"]),
    )


def build_condition(payload: object) -> ClaimCondition | None:
    """Read a declared condition, refusing one this checker cannot settle.

    Returns None for an absent declaration. Raises for a malformed one: a
    producer that tried to declare a condition and got it wrong must not be
    treated the same as one that declared none.
    """
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise TypeError(f"claim_check must be an object, got {type(payload).__name__}")
    kind = str(payload.get("kind", ""))
    if kind not in SUPPORTED_KINDS:
        raise ValueError(
            f"claim_check kind must be one of {sorted(SUPPORTED_KINDS)}, got {kind!r}"
        )
    return ClaimCondition(
        kind=ConditionKind(kind),
        source_id=str(payload["source_id"]),
        text=str(payload["text"]),
    )


def _observed_text(
    finding: Finding,
    source_id: str,
    observations: list[Observation],
    root: str | Path,
    readers: dict[str, SourceReader] | None = None,
) -> tuple[Observation, str] | ClaimVerdict:
    """The lines the run actually recorded, re-read and re-checked.

    Returns a verdict instead when nothing can be settled. Every refusal here
    is `source_unavailable` or `source_not_cited`: a source that cannot be
    established decides nothing in either direction, because refuting a claim
    with content the run never observed would be as wrong as supporting it.
    """
    cited = {reference.source_id for reference in finding.evidence}
    if source_id not in cited:
        return ClaimVerdict(
            result=ClaimResult.SOURCE_NOT_CITED,
            reason=(
                f"the check is about {source_id}, which this finding does not cite; "
                "a claim is settled against what it points at"
            ),
        )

    by_id = {observation.source_id: observation for observation in observations}
    observation = by_id.get(source_id)
    if observation is None:
        return ClaimVerdict(
            result=ClaimResult.SOURCE_UNAVAILABLE,
            reason=f"{source_id} was not read in this run",
        )

    reader = resolve_readers(root, readers).get(observation.source_type)
    if reader is None:
        return ClaimVerdict(
            result=ClaimResult.UNSUPPORTED_KIND,
            reason=(
                f"this run has no reader for a {observation.source_type!r} source, so "
                "its current state cannot be established"
            ),
        )

    try:
        content = reader.read(observation)
    except PathRefused:
        return ClaimVerdict(
            result=ClaimResult.SOURCE_UNAVAILABLE,
            reason=f"{observation.path} resolves outside the snapshot root",
        )
    except OSError:
        return ClaimVerdict(
            result=ClaimResult.SOURCE_UNAVAILABLE,
            reason=f"{observation.path} is no longer readable",
        )

    if sha256_text(content) != observation.content_sha256:
        return ClaimVerdict(
            result=ClaimResult.SOURCE_UNAVAILABLE,
            reason=f"{observation.path} has changed since it was observed",
        )

    observed = "\n".join(
        content.splitlines()[observation.line_start - 1 : observation.line_end]
    )
    if observed != observation.excerpt:
        return ClaimVerdict(
            result=ClaimResult.SOURCE_UNAVAILABLE,
            reason=(
                f"{observation.path} no longer matches the excerpt the run recorded "
                "for those lines"
            ),
        )
    return observation, observed


def check_typed_claim(
    finding: Finding,
    claim: TypedClaim | None,
    observations: list[Observation],
    root: str | Path,
    readers: dict[str, SourceReader] | None = None,
) -> ClaimVerdict:
    """Settle a typed claim against the lines the run observed.

    Call this only for a finding whose citations are already sound. A
    refutation resting on a source the finding cannot point at would be an
    accusation about the wrong file.
    """
    if claim is None:
        return ClaimVerdict(
            result=ClaimResult.NOT_DECLARED,
            reason=(
                "the finding states free text rather than a claim this checker can "
                "settle, so its truth was not established"
            ),
        )

    resolved = _observed_text(finding, claim.source_id, observations, root, readers)
    if isinstance(resolved, ClaimVerdict):
        return resolved
    observation, observed = resolved

    # The sentence a reader sees has to be the sentence that was tested.
    # Without this, a typed claim could be settled while the prose beside it
    # asserted something broader.
    expected = claim.render(observation.path, observation.line_start, observation.line_end)
    if finding.claim.strip() != expected:
        return ClaimVerdict(
            result=ClaimResult.CLAIM_TEXT_MISMATCH,
            reason=(
                "the finding's text is not what its typed claim says. Expected "
                f"exactly: {expected!r}"
            ),
            checked={"expected_claim": expected},
        )

    checked = {
        "kind": claim.kind.value,
        "source_id": claim.source_id,
        "text": claim.text,
        "path": observation.path,
        "line_start": observation.line_start,
        "line_end": observation.line_end,
    }
    if claim.holds_for(observed):
        return ClaimVerdict(
            result=ClaimResult.VERIFIED,
            reason=f"{expected} — settled against the lines this run recorded",
            checked=checked,
        )
    return ClaimVerdict(
        result=ClaimResult.CONTRADICTED,
        reason=f"the source refutes the finding: {expected} is false",
        checked=checked,
    )


def check_condition(
    finding: Finding,
    condition: ClaimCondition | None,
    observations: list[Observation],
    root: str | Path,
    readers: dict[str, SourceReader] | None = None,
) -> ClaimVerdict:
    """Settle a producer's free-standing test. Never decisive.

    Whether this test is a fair test of the finding's free text is exactly what
    is not checked, so the results are named for the condition and not for the
    claim.
    """
    if condition is None:
        return ClaimVerdict(
            result=ClaimResult.NOT_DECLARED,
            reason=(
                "the finding states free text and declares no test of it, so nothing "
                "about the claim was checked"
            ),
        )

    resolved = _observed_text(finding, condition.source_id, observations, root, readers)
    if isinstance(resolved, ClaimVerdict):
        return resolved
    observation, observed = resolved

    checked = {
        "kind": condition.kind.value,
        "source_id": condition.source_id,
        "text": condition.text,
        "path": observation.path,
        "line_start": observation.line_start,
        "line_end": observation.line_end,
    }
    held = condition.holds_for(observed)
    return ClaimVerdict(
        result=(
            ClaimResult.CONDITION_SUPPORTED if held else ClaimResult.CONDITION_REFUTED
        ),
        reason=(
            f"the producer's own test ({condition.kind.value}: {condition.text!r} in "
            f"{observation.path} lines {observation.line_start}-{observation.line_end}) "
            + ("held" if held else "failed")
            + ". Nothing checked that this test is a fair test of the finding's text, "
            "so it settles the test and not the claim"
        ),
        checked=checked,
    )


def check_claim(
    finding: Finding,
    typed: TypedClaim | None,
    condition: ClaimCondition | None,
    observations: list[Observation],
    root: str | Path,
    readers: dict[str, SourceReader] | None = None,
) -> ClaimVerdict:
    """Settle a finding as far as its form allows.

    A typed claim is settled as the claim. Otherwise a declared condition is
    settled as a condition, which records something without deciding anything.
    """
    if typed is not None:
        return check_typed_claim(finding, typed, observations, root, readers)
    return check_condition(finding, condition, observations, root, readers)


def apply_verdict(finding: Finding, evidence: Any, claim: ClaimVerdict) -> Finding:
    """Record both checks on the finding.

    The only place `verified` and `contradicted` are constructed, and it lives
    here rather than in `finding.py` so that module's structural guarantee
    stays exactly as strong as it was. Reaching either requires a typed claim
    settled against observed lines — a settled *condition* never does, however
    cleanly it was settled.

    Sound citations are a precondition, not a contribution: a refutation
    resting on a source the finding cannot point at would be an accusation
    about the wrong file.
    """
    verdict: str = "insufficient_evidence"
    method: str = "deterministic_evidence_check"
    if evidence.citations_are_sound() and claim.is_decisive():
        verdict = claim.result.value
        method = "semantic"

    limitations = list(finding.limitations)
    for note in (evidence.reason, claim.reason):
        if note not in limitations:
            limitations.append(note)

    return Finding(
        finding_id=finding.finding_id,
        claim=finding.claim,
        scope=finding.scope,
        # P1.1 box three: a declared severity survives only a verdict that
        # established the claim. See `finding.severity_after`.
        severity=severity_after(verdict, finding),
        declared_severity=finding.declared_severity,
        severity_rationale=finding.severity_rationale,
        evidence=finding.evidence,
        verification_method=method,  # type: ignore[arg-type]
        verdict=verdict,  # type: ignore[arg-type]
        limitations=limitations,
        reproducible_command=finding.reproducible_command,
    )


__all__ = [
    "CLAIM_KINDS",
    "DECISIVE",
    "SUPPORTED_KINDS",
    "ClaimCondition",
    "ClaimKind",
    "ClaimResult",
    "ClaimVerdict",
    "ConditionKind",
    "TypedClaim",
    "apply_verdict",
    "build_condition",
    "build_typed_claim",
    "check_claim",
    "check_condition",
    "check_typed_claim",
]
