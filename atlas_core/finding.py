"""Finding.v1 — a claim, what it points at, and how far that has been checked.

ROADMAP.md P0.2. The rule this module is shaped by:

    Om semantisk verifiering inte kan göras: `insufficient_evidence`,
    aldrig `verified` på enbart filnamn.

`check_finding` is therefore built so that `verified` is **unreachable** from
it. It can establish that a citation is sound — the source was read in this
run, the digest matches what the finding claims, and the quoted text really
sits at the line range it names — and none of that says the source *supports*
the claim. A sound citation and a broken one therefore earn the *same* verdict,
`insufficient_evidence`; which of the two it was lives in
`citations_are_sound()`. Granting `verified` for an intact pointer is precisely the
substitution of citation for verification that this phase removes, so the code
cannot express it.

That makes this layer a filter rather than a judge. It rules claims out. Ruling
one *in* needs a semantic check on top, which `claim_check` performs for a
*typed* claim — one stated as literal presence or absence over observed lines,
where the claim is its own predicate. A free-text claim gets no verdict from
either layer, and the roadmap is explicit that a model's own opinion of its
output may not close that gap.

A `Finding` never asserts its own verdict either: it is constructed
`insufficient_evidence` with method `none`, and a checker attaches a result via
`EvidenceCheck.apply_to`.

`contradicted` is equally out of reach here. A citation being unusable — an
unknown id, a wrong digest, a quote that is not where it claims — says the
*pointer* is broken, not that the claim is false. A correct finding can cite
its source badly. Both outcomes are therefore `insufficient_evidence`, and the
discrimination consumers need lives in `citations_are_sound()` and the
per-citation statuses rather than in a verdict word that would read as a
refutation.

## Scope

This is a standalone deterministic filter. It is **not** wired into
`AtlasController` or the existing `repo_review` evaluator, so a run today gains
no new protection against a wrong `PASS` from it. The P0.2 boxes stay open
until the filter is part of an actual run.

It also reads local files only. A `github_file`, `ci` or `memory` observation
returns `unsupported_source_type` rather than being checked against a local
path that happens to match.

## What a citation is checked against

The run's own recorded observation, not the file alone. Three things have to
agree, all against the bytes of a single read:

1. the observation's digest still describes the file,
2. the observation's **own excerpt** still matches the line range it claims,
3. the finding's quote sits at its line range, **inside** the range the
   observation recorded.

Dropping (2) would let a finding rest on an observation that misquotes its own
source, and dropping (3) would let a finding cite lines the run never read — a
correct-looking quote lifted from a part of the file no observation covers. A
finding may only cite what was actually observed; to cite further, collect an
observation that covers those lines.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Final, Literal

from .integrity import PathRefused, read_within
from .observation import UNKNOWN, Observation
from .snapshot import sha256_text

SCHEMA: Final = "atlas-finding.v1"

Verdict = Literal["verified", "contradicted", "insufficient_evidence"]
Severity = Literal["P0", "P1", "P2", "unknown"]
VerificationMethod = Literal[
    "none", "deterministic_evidence_check", "semantic", "test_execution"
]

SEVERITIES: tuple[str, ...] = ("P0", "P1", "P2", UNKNOWN)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class EvidenceStatus(str, Enum):
    """What a deterministic check could establish about one citation.

    Every value except INTACT says the *citation* is unusable. None of them
    says the claim is false — a finding can be entirely correct and cite its
    source badly. That distinction is why none of these produce a
    `contradicted` verdict.
    """

    #: The source_id names nothing this run read.
    UNKNOWN_SOURCE = "unknown_source"
    #: The finding claims a digest the observation does not have.
    DIGEST_MISMATCH = "digest_mismatch"
    #: The quoted text is not what sits at the claimed line range.
    QUOTE_MISMATCH = "quote_mismatch"
    #: The source has changed or gone since it was read.
    STALE_SOURCE = "stale_source"
    #: The source is not a kind this checker can verify. See SUPPORTED_SOURCE_TYPES.
    UNSUPPORTED_SOURCE_TYPE = "unsupported_source_type"
    #: The observation's path resolves outside the snapshot root, or the file
    #: could not be opened safely at the moment of the read.
    PATH_REFUSED = "path_refused"
    #: The observation's own excerpt is not what sits at the lines it claims.
    EXCERPT_MISMATCH = "excerpt_mismatch"
    #: The citation names lines the observation never recorded.
    QUOTE_OUTSIDE_EXCERPT = "quote_outside_excerpt"
    #: Pointer is sound. Says nothing about whether it supports the claim.
    INTACT = "intact"


#: This checker reads local files. A `github_file`, `ci` or `memory`
#: observation needs its own adapter to establish provenance, and checking one
#: against a local path that happens to match would be a false confirmation.
SUPPORTED_SOURCE_TYPES: frozenset[str] = frozenset({"local_file"})


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

    def citations_are_sound(self) -> bool:
        """Whether every citation points at something this run can stand behind.

        This is the discrimination the verdict deliberately does not carry. A
        broken citation and an unchecked claim are both `insufficient_evidence`,
        because neither establishes anything — but they need different repairs.
        A broken citation is the producer's error to fix; an unchecked claim
        needs a semantic pass.
        """
        return bool(self.statuses) and all(
            status is EvidenceStatus.INTACT for _, status in self.statuses
        )

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

    Always returns `insufficient_evidence`. `verified` and `contradicted` are
    both unreachable from here: an intact pointer does not show that the source
    supports the claim, and a broken pointer does not show that the claim is
    false. `citations_are_sound()` separates those two cases, and the
    per-citation statuses say which check failed.
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

    broken = [
        (source_id, status)
        for source_id, status in statuses
        if status is not EvidenceStatus.INTACT
    ]
    if broken:
        # Not `contradicted`. A citation being unusable says nothing about
        # whether the claim is false — a correct finding can cite its source
        # badly. Disproving a claim is the semantic layer's job, and taking
        # that word here would let a broken pointer read as a refutation.
        return EvidenceCheck(
            verdict="insufficient_evidence",
            reason="citations are unusable: "
            + "; ".join(f"{source_id}: {status.value}" for source_id, status in broken),
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

    # A github_file, ci or memory observation must not be read off the local
    # disk: a local path that happens to match would confirm the wrong thing.
    if observation.source_type not in SUPPORTED_SOURCE_TYPES:
        return EvidenceStatus.UNSUPPORTED_SOURCE_TYPE

    # The finding's claimed digest must match what was observed. This is what
    # stops a citation naming a real source while describing a different
    # version of it. Pure comparison, no read.
    if ref.content_sha256 != observation.content_sha256:
        return EvidenceStatus.DIGEST_MISMATCH

    # A finding may only cite what the run recorded. An excerpt is bounded, so
    # a quote beyond it can be perfectly accurate about the file and still rest
    # on lines no observation covers — which is the citation standing in for an
    # observation that was never made. Pure comparison, no read.
    if ref.line_start < observation.line_start or ref.line_end > observation.line_end:
        return EvidenceStatus.QUOTE_OUTSIDE_EXCERPT

    # One read, feeding every check below. Reading twice — once to confirm
    # freshness and once to confirm the quote — leaves a window in which the
    # file can change between them, so the digest would describe content the
    # quote was never compared against.
    #
    # Containment belongs to this read, not to an earlier one. `Observation.path`
    # is a plain string that accepts `../` and absolute forms, the collection
    # wrapper in `integrity` does not cover a re-read, and a name checked before
    # an open can be a link by the time the open happens. `read_within` refuses
    # on all three grounds and returns the bytes it actually opened.
    try:
        content = read_within(root, observation.path)
    except PathRefused:
        return EvidenceStatus.PATH_REFUSED
    except OSError:
        return EvidenceStatus.STALE_SOURCE

    if sha256_text(content) != observation.content_sha256:
        return EvidenceStatus.STALE_SOURCE

    # The observation has to still be honest about itself. The digest says the
    # file is unchanged; it says nothing about whether the excerpt this run
    # exported ever matched the lines it names. `verify_observation` checked
    # this, and folding the two reads into one dropped it.
    if _lines(content, observation.line_start, observation.line_end) != observation.excerpt:
        return EvidenceStatus.EXCERPT_MISMATCH

    # The quote has to be what sits at those lines, contiguously, in the same
    # bytes the digest just confirmed. Text lifted from elsewhere in the file
    # is a cherry-pick, not a citation.
    if _lines(content, ref.line_start, ref.line_end) != ref.quoted:
        return EvidenceStatus.QUOTE_MISMATCH

    return EvidenceStatus.INTACT


def _lines(content: str, line_start: int, line_end: int) -> str:
    return "\n".join(content.splitlines()[line_start - 1 : line_end])


def _derive_finding_id(claim: str, scope: str) -> str:
    digest = hashlib.sha256("\0".join((claim, scope)).encode("utf-8")).hexdigest()
    return digest[:16]


__all__ = [
    "SCHEMA",
    "SEVERITIES",
    "SUPPORTED_SOURCE_TYPES",
    "EvidenceCheck",
    "EvidenceRef",
    "EvidenceStatus",
    "Finding",
    "Severity",
    "VerificationMethod",
    "Verdict",
    "check_finding",
]
