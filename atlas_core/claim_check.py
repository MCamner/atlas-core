"""P0.2b: deciding whether the source supports the claim.

ROADMAP.md P0.2, the half PR D and PR F could not reach. Citation integrity
established that a pointer holds. It said nothing about the claim, and the gap
was demonstrable: a README containing `pip install atlas-core` backed a finding
asserting that it "saknar helt installationsinstruktioner och nämner aldrig
pip", with a perfectly sound citation and `passed: True`.

## The model is not its own judge

The roadmap's rule is that a model's self-assessment may not close this on its
own, so nothing here asks a producer whether it was right. What a producer must
supply instead is **what would make its claim false** — a falsifiable condition
over a source the run actually read. A deterministic checker then decides.

That splits the labour honestly. Stating a refutable condition is a job for
whoever wrote the claim; deciding whether the condition holds is a job for code
that cannot want a particular answer.

## Refutation is stronger than support

The two outcomes are not symmetric, and the module treats them differently.

`contradicted` needs one counterexample: the producer said the text would be
absent, and it is there. The declared condition does the work, and no judgement
about wording is involved.

`verified` is weaker. It says the declared condition held — not that the
condition captures the claim. A producer that declares an easy condition gets
an easy `verified`, and nothing here detects that. So `verified` means "the
falsifiable condition this finding named turned out to hold", and the evaluator
says so in those terms rather than presenting the claim as established.

That residual is why P0.2's boxes describe what is checked rather than claiming
the claims are true. Closing it needs correspondence between a claim and its
condition, which is not a deterministic problem.

## Literal text only

Conditions match literal substrings. Regular expressions are not accepted: a
pattern supplied by a producer is untrusted input, and a crafted one can hang
the checker. A literal search cannot.

The read follows the same discipline as `finding.check_finding` — one read,
through `integrity.read_within`, refusing a path that escapes the snapshot, and
rejecting content whose digest no longer matches. A stale source decides
nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from .finding import Finding
from .integrity import PathRefused, read_within
from .observation import Observation
from .snapshot import sha256_text


class ClaimKind(str, Enum):
    """What a finding asserts about its source, in a form code can settle."""

    #: The source does not contain this text. Refuted by finding it.
    ABSENT = "absent"
    #: The source contains this text. Refuted by not finding it.
    PRESENT = "present"


SUPPORTED_KINDS: frozenset[str] = frozenset(kind.value for kind in ClaimKind)


class ClaimResult(str, Enum):
    """What the deterministic check could settle about the claim itself."""

    #: The declared condition held. See "Refutation is stronger than support".
    SUPPORTED = "supported"
    #: The source refutes what the finding said would be true of it.
    REFUTED = "refuted"
    #: No condition was declared, so nothing was checked.
    NOT_DECLARED = "not_declared"
    #: A condition was declared in a form this checker cannot settle.
    UNSUPPORTED_KIND = "unsupported_kind"
    #: The condition names a source the finding does not cite.
    SOURCE_NOT_CITED = "source_not_cited"
    #: The source could not be read, or has moved since it was observed.
    SOURCE_UNAVAILABLE = "source_unavailable"


@dataclass(frozen=True)
class ClaimCondition:
    """The falsifiable condition a finding declares about one of its sources."""

    kind: ClaimKind
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

    def holds_for(self, content: str) -> bool:
        if self.kind is ClaimKind.ABSENT:
            return self.text not in content
        return self.text in content


@dataclass(frozen=True)
class ClaimVerdict:
    """The outcome of checking a claim, and what it is worth."""

    result: ClaimResult
    reason: str
    #: The condition that was evaluated, so a reader can judge whether it was
    #: a fair test of the claim. Null when none was declared or usable.
    condition: ClaimCondition | None = None

    def refutes(self) -> bool:
        return self.result is ClaimResult.REFUTED

    def supports(self) -> bool:
        """Whether the declared condition held.

        Deliberately not called `is_true`. It says the finding named a way to
        be wrong and was not wrong in that way.
        """
        return self.result is ClaimResult.SUPPORTED

    def to_dict(self) -> dict[str, Any]:
        return {
            "result": self.result.value,
            "reason": self.reason,
            "condition": (
                {
                    "kind": self.condition.kind.value,
                    "source_id": self.condition.source_id,
                    "text": self.condition.text,
                }
                if self.condition
                else None
            ),
        }


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
        kind=ClaimKind(kind),
        source_id=str(payload["source_id"]),
        text=str(payload["text"]),
    )


def check_claim(
    finding: Finding,
    condition: ClaimCondition | None,
    observations: list[Observation],
    root: str | Path,
) -> ClaimVerdict:
    """Settle a finding's declared condition against the source it cites.

    Call this only for a finding whose citations are already sound. Checking a
    claim against a source the finding cannot correctly point at would decide
    nothing, and a `refuted` from such a check would be an accusation resting
    on the wrong file.
    """
    if condition is None:
        return ClaimVerdict(
            result=ClaimResult.NOT_DECLARED,
            reason=(
                "the finding declares no condition that could refute it, so nothing "
                "about the claim itself was checked"
            ),
        )

    cited = {reference.source_id for reference in finding.evidence}
    if condition.source_id not in cited:
        return ClaimVerdict(
            result=ClaimResult.SOURCE_NOT_CITED,
            reason=(
                f"the condition is about {condition.source_id}, which this finding "
                "does not cite; a claim is checked against what it points at"
            ),
            condition=condition,
        )

    by_id = {observation.source_id: observation for observation in observations}
    observation = by_id.get(condition.source_id)
    if observation is None:
        return ClaimVerdict(
            result=ClaimResult.SOURCE_UNAVAILABLE,
            reason=f"{condition.source_id} was not read in this run",
            condition=condition,
        )

    try:
        content = read_within(root, observation.path)
    except PathRefused:
        return ClaimVerdict(
            result=ClaimResult.SOURCE_UNAVAILABLE,
            reason=f"{observation.path} resolves outside the snapshot root",
            condition=condition,
        )
    except OSError:
        return ClaimVerdict(
            result=ClaimResult.SOURCE_UNAVAILABLE,
            reason=f"{observation.path} is no longer readable",
            condition=condition,
        )

    # A source that has moved decides nothing, in either direction. Refuting a
    # claim with content the run never observed would be as wrong as
    # supporting one with it.
    if sha256_text(content) != observation.content_sha256:
        return ClaimVerdict(
            result=ClaimResult.SOURCE_UNAVAILABLE,
            reason=f"{observation.path} has changed since it was observed",
            condition=condition,
        )

    if condition.holds_for(content):
        return ClaimVerdict(
            result=ClaimResult.SUPPORTED,
            reason=(
                f"the condition the finding named ({condition.kind.value}: "
                f"{condition.text!r}) holds in {observation.path}. That is what was "
                "checked — not that the condition captures the claim"
            ),
            condition=condition,
        )

    return ClaimVerdict(
        result=ClaimResult.REFUTED,
        reason=(
            f"{observation.path} refutes the finding: it said {condition.text!r} would "
            f"be {condition.kind.value}, and the opposite is true"
        ),
        condition=condition,
    )


def apply_verdict(
    finding: Finding, evidence: Any, claim: ClaimVerdict
) -> Finding:
    """Record both checks on the finding.

    This is the only place `verified` and `contradicted` are constructed, and
    it lives here rather than in `finding.py` so that module's structural
    guarantee — a citation checker cannot hand out either word — stays exactly
    as strong as it was. Reaching them requires a declared, refutable condition
    and a source that settled it.

    Sound citations are a precondition, not a contribution: a refutation
    resting on a source the finding cannot point at would be an accusation
    about the wrong file.
    """
    verdict: str = "insufficient_evidence"
    method: str = "deterministic_evidence_check"
    if evidence.citations_are_sound():
        if claim.refutes():
            verdict, method = "contradicted", "semantic"
        elif claim.supports():
            verdict, method = "verified", "semantic"

    limitations = list(finding.limitations)
    for note in (evidence.reason, claim.reason):
        if note not in limitations:
            limitations.append(note)

    return Finding(
        finding_id=finding.finding_id,
        claim=finding.claim,
        scope=finding.scope,
        severity=finding.severity,
        severity_rationale=finding.severity_rationale,
        evidence=finding.evidence,
        verification_method=method,  # type: ignore[arg-type]
        verdict=verdict,  # type: ignore[arg-type]
        limitations=limitations,
        reproducible_command=finding.reproducible_command,
    )


__all__ = [
    "apply_verdict",
    "SUPPORTED_KINDS",
    "ClaimCondition",
    "ClaimKind",
    "ClaimResult",
    "ClaimVerdict",
    "build_condition",
    "check_claim",
]
