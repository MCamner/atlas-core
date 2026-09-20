"""Finding.v1 — a claim, what it points at, and how far that has been checked.

ROADMAP.md P0.2. The rule this module is shaped by:

    Om semantisk verifiering inte kan göras: `insufficient_evidence`,
    aldrig `verified` på enbart filnamn.

`check_finding` is therefore built so that `verified` is **unreachable** from
it. It can establish that a citation is sound — the source was read in this
run, the digest matches what the finding claims, and the quoted text really
sits at the line range it names — and none of that says the source *supports*
the claim. A sound citation earns `insufficient_evidence`; a broken one earns
`contradicted`. Granting `verified` for an intact pointer is precisely the
substitution of citation for verification that this phase removes, so the code
cannot express it.

That makes this layer a filter rather than a judge. It rules claims out. Ruling
one *in* needs a semantic check on top, which is P0.2b, and the roadmap is
explicit that a model's own opinion of its output may not close that gap alone.

A `Finding` never asserts its own verdict either: it is constructed
`insufficient_evidence` with method `none`, and a checker attaches a result via
`EvidenceCheck.apply_to`.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Final, Literal

from .observation import UNKNOWN, Observation
from .snapshot import verify_observation

SCHEMA: Final = "atlas-finding.v1"

Verdict = Literal["verified", "contradicted", "insufficient_evidence"]
Severity = Literal["P0", "P1", "P2", "unknown"]
VerificationMethod = Literal[
    "none", "deterministic_evidence_check", "semantic", "test_execution"
]

SEVERITIES: tuple[str, ...] = ("P0", "P1", "P2", UNKNOWN)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class EvidenceStatus(str, Enum):
    """What a deterministic check could establish about one citation."""

    #: The source_id names nothing this run read.
    UNKNOWN_SOURCE = "unknown_source"
    #: The finding claims a digest the observation does not have.
    DIGEST_MISMATCH = "digest_mismatch"
    #: The quoted text is not what sits at the claimed line range.
    QUOTE_MISMATCH = "quote_mismatch"
    #: The source has changed or gone since it was read.
    STALE_SOURCE = "stale_source"
    #: Pointer is sound. Says nothing about whether it supports the claim.
    INTACT = "intact"


@dataclass(frozen=True)
class EvidenceRef:
    """What a finding claims about the source it cites.

    These are the finding's *assertions*, checked against the run's
    observations — not copied from them. Copying would make every citation
    trivially correct and the check meaningless.
    """

    source_id: str
    content_sha256: str
    line_start: int
    line_end: int
    quoted: str

    def __post_init__(self) -> None:
        if not _SHA256.match(self.content_sha256):
            raise ValueError(
                f"content_sha256 must be 64 lowercase hex characters, got "
                f"{self.content_sha256!r}"
            )
        if self.line_start < 1:
            raise ValueError("line_start is 1-based")
        if self.line_end < self.line_start:
            raise ValueError(
                f"line range must run forwards, got {self.line_start}..{self.line_end}"
            )
        if not self.quoted:
            raise ValueError("a citation must quote what it relies on")


@dataclass(frozen=True)
class Finding:
    """One claim, its citations, and how far it has been checked."""

    finding_id: str
    claim: str
    scope: str
    severity: Severity
    severity_rationale: str
    evidence: list[EvidenceRef]
    verification_method: VerificationMethod = "none"
    verdict: Verdict = "insufficient_evidence"
    limitations: list[str] = field(default_factory=list)
    reproducible_command: str = UNKNOWN

    def __post_init__(self) -> None:
        if not self.claim.strip():
            raise ValueError("a finding must state a claim")
        if not self.scope.strip():
            raise ValueError("a finding must state its scope")
        if self.severity not in SEVERITIES:
            raise ValueError(f"severity must be one of {SEVERITIES}, got {self.severity!r}")
        # A severity without a reason is a number someone can quote back at you
        # as though it were assessed.
        if not self.severity_rationale.strip():
            raise ValueError("severity must carry a rationale")
        if not self.reproducible_command.strip():
            raise ValueError(
                f"reproducible_command must be a command or {UNKNOWN!r}, not blank"
            )

    @classmethod
    def create(
        cls,
        *,
        claim: str,
        scope: str,
        severity: str,
        severity_rationale: str,
        evidence: list[EvidenceRef],
        limitations: list[str] | None = None,
        reproducible_command: str = UNKNOWN,
    ) -> Finding:
        """Build an unverified finding. Verdicts are attached by a checker."""
        return cls(
            finding_id=_derive_finding_id(claim, scope),
            claim=claim,
            scope=scope,
            severity=severity,  # type: ignore[arg-type]
            severity_rationale=severity_rationale,
            evidence=list(evidence),
            limitations=list(limitations or []),
            reproducible_command=reproducible_command,
        )

    def to_dict(self) -> dict[str, Any]:
        return {"schema": SCHEMA, **asdict(self)}


@dataclass(frozen=True)
class EvidenceCheck:
    """The outcome of checking a finding's citations, and why."""

    verdict: Verdict
    reason: str
    statuses: list[tuple[str, EvidenceStatus]]

    def is_supported(self) -> bool:
        """Whether the claim may be presented as established.

        Only `verified` qualifies, and this layer cannot produce it. Intact
        citations are necessary and not sufficient.
        """
        return self.verdict == "verified"

    def apply_to(self, finding: Finding) -> Finding:
        """Record this outcome on the finding, without upgrading it."""
        limitations = list(finding.limitations)
        if self.reason not in limitations:
            limitations.append(self.reason)
        return Finding(
            finding_id=finding.finding_id,
            claim=finding.claim,
            scope=finding.scope,
            severity=finding.severity,
            severity_rationale=finding.severity_rationale,
            evidence=finding.evidence,
            verification_method="deterministic_evidence_check",
            verdict=self.verdict,
            limitations=limitations,
            reproducible_command=finding.reproducible_command,
        )


def check_finding(
    finding: Finding, observations: list[Observation], root: str | Path
) -> EvidenceCheck:
    """Check a finding's citations against what this run actually read.

    Returns `contradicted` when any citation is unsound, and
    `insufficient_evidence` otherwise — including when every citation is
    perfect. `verified` is never returned: whether an intact source supports
    the claim is a different question, and answering it deterministically is
    not possible here.
    """
    if not finding.evidence:
        return EvidenceCheck(
            verdict="insufficient_evidence",
            reason="finding cites no evidence, so nothing supports it",
            statuses=[],
        )

    by_id = {observation.source_id: observation for observation in observations}
    statuses = [
        (ref.source_id, _check_reference(ref, by_id, root)) for ref in finding.evidence
    ]

    broken = [(source_id, status) for source_id, status in statuses if status is not EvidenceStatus.INTACT]
    if broken:
        return EvidenceCheck(
            verdict="contradicted",
            reason="; ".join(
                f"{source_id}: {status.value}" for source_id, status in broken
            ),
            statuses=statuses,
        )

    return EvidenceCheck(
        verdict="insufficient_evidence",
        reason=(
            "citations are intact, but no semantic check has established that "
            "the source supports the claim"
        ),
        statuses=statuses,
    )


def _check_reference(
    ref: EvidenceRef, by_id: dict[str, Observation], root: str | Path
) -> EvidenceStatus:
    observation = by_id.get(ref.source_id)
    if observation is None:
        return EvidenceStatus.UNKNOWN_SOURCE

    # The finding's claimed digest must match what was observed. This is what
    # stops a citation naming a real source while describing a different
    # version of it.
    if ref.content_sha256 != observation.content_sha256:
        return EvidenceStatus.DIGEST_MISMATCH

    verification = verify_observation(observation, root)
    if not verification.is_evidence():
        return EvidenceStatus.STALE_SOURCE

    path = Path(root).expanduser().resolve() / observation.path
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return EvidenceStatus.STALE_SOURCE

    # The quote has to be what sits at those lines, contiguously. Text lifted
    # from elsewhere in the file is a cherry-pick, not a citation.
    actual = "\n".join(content.splitlines()[ref.line_start - 1 : ref.line_end])
    if actual != ref.quoted:
        return EvidenceStatus.QUOTE_MISMATCH

    return EvidenceStatus.INTACT


def _derive_finding_id(claim: str, scope: str) -> str:
    digest = hashlib.sha256("\0".join((claim, scope)).encode("utf-8")).hexdigest()
    return digest[:16]


__all__ = [
    "SCHEMA",
    "SEVERITIES",
    "EvidenceCheck",
    "EvidenceRef",
    "EvidenceStatus",
    "Finding",
    "Severity",
    "VerificationMethod",
    "Verdict",
    "check_finding",
]
