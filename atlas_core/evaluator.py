"""How a run is graded, and what it takes for evidence to count.

Two grading paths live here, and which one runs depends on what the run
actually carries — never on how the output is worded:

- **Citation only.** A run with `list[str]` context is graded as it always was:
  a finding must name a source that was read. That check is shallow by
  construction; it cannot tell a true claim from a false one about the same
  file, and the reasons it emits say so.
- **Deterministic evidence.** A run carrying an `EvidenceBase` is graded with
  `check_finding`, against observations that can be re-read and re-hashed. A
  finding must carry a machine-readable citation, and that citation must still
  survive.

Sound citations do **not** mean `verified`. They mean a claim is eligible for a
semantic check that this repository does not perform yet (P0.2b). A run whose
citations are all sound therefore still passes on formatting plus citation
integrity, and the reasons say exactly that rather than implying the claims
were confirmed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .state import AtlasEvaluation
from .safety import requires_write_approval
from .evidence_base import EvidenceBase
from .finding import EvidenceStatus, Finding, check_finding
from .evidence import (
    FINDINGS_FENCE,
    cites_a_source,
    findings_in,
    observed_sources,
    structured_findings,
)

PASS_THRESHOLD = 0.78


@dataclass(frozen=True)
class RouteEvaluator:
    """What it takes for one kind of task to count as actually done.

    Formatting is graded the same way for every route. This is the part that
    differs: whether the route makes claims about something it had to read,
    and therefore has to show its sources.
    """

    # Where the output attests which sources it read. That attestation says the
    # files were observed — nothing about whether any claim is factually right.
    evidence_heading: str
    # Where the output makes claims that must cite a source to count.
    finding_headings: tuple[str, ...]
    requires_sources: bool
    min_coverage: float = 1.0


# Per P1, read-only repository review comes first. A route with no entry here
# is graded on formatting alone, exactly as it was before.
ROUTE_EVALUATORS: dict[str, RouteEvaluator] = {
    "repo_review": RouteEvaluator(
        evidence_heading="## Observed sources",
        finding_headings=("## Verified findings",),
        requires_sources=True,
    ),
}

EVIDENCE_PROSE = {
    "no_sources_observed": (
        "No verifiable source was observed, so no finding about the repository "
        "can be supported."
    ),
    "sources_not_documented": (
        "Sources were read but the output does not record which ones."
    ),
    "uncited_findings": "Some findings cite no observed source.",
    "malformed_findings": (
        "The machine-readable findings block is present but could not be read, "
        "so no citation in it could be checked."
    ),
    "uncheckable_findings": (
        "Some findings carry no machine-readable citation, so nothing about "
        "them could be checked against what was read."
    ),
    "unsound_citations": (
        "Some findings cite a source that does not hold up: unknown id, a "
        "digest or quote that does not match, or a source that has moved."
    ),
}

#: Failures a differently-worded citation could repair. Everything else needs a
#: fresh observation or an adapter that does not exist yet, so retrying the same
#: run cannot close it — and burning an iteration to fail again is worse than
#: stopping and saying why.
_REQUOTABLE: frozenset[EvidenceStatus] = frozenset(
    {
        EvidenceStatus.UNKNOWN_SOURCE,
        EvidenceStatus.DIGEST_MISMATCH,
        EvidenceStatus.QUOTE_MISMATCH,
        EvidenceStatus.QUOTE_OUTSIDE_EXCERPT,
    }
)

# Section markers every route output is expected to carry. The codes are the
# contract between the evaluator (which reports gaps) and the executor (which
# closes them on a retry), so neither side has to parse the other's prose.
REQUIRED_SECTIONS: dict[str, tuple[str, ...]] = {
    "recommendation": ("## Recommendation", "## Recommended", "## Rekommendation"),
    "next_step": ("## Next step", "## Recommended next step", "## Nästa steg"),
    "confidence": ("## Confidence", "## Konfidens"),
}

SECTION_WEIGHTS = {"recommendation": 0.15, "next_step": 0.10, "confidence": 0.05}

SECTION_PROSE = {
    "recommendation": "No clear recommendation section.",
    "next_step": "No clear next step.",
    "confidence": "Confidence is missing.",
}

SECTION_PRESENT = {
    "recommendation": "Contains recommendation.",
    "next_step": "Contains next step.",
    "confidence": "Contains confidence.",
}


def missing_sections(output: str) -> list[str]:
    """Return the codes of required sections the output does not contain."""
    return [
        code
        for code, markers in REQUIRED_SECTIONS.items()
        if not any(marker in output for marker in markers)
    ]


def evaluate(
    task: str,
    output: str,
    validation_focus: list[str],
    iteration: int,
    max_iterations: int,
    *,
    route_name: str | None = None,
    observations: list[str] | None = None,
    evidence_base: EvidenceBase | None = None,
) -> AtlasEvaluation:
    reasons: list[str] = []
    missing: list[str] = []
    score = 0.45
    if len(output.strip()) > 300:
        score += 0.15
        reasons.append("Output has enough substance.")
    else:
        missing.append("Output may be too short.")

    gaps = missing_sections(output)
    for code in REQUIRED_SECTIONS:
        if code in gaps:
            missing.append(SECTION_PROSE[code])
        else:
            score += SECTION_WEIGHTS[code]
            reasons.append(SECTION_PRESENT[code])

    if "no_unverified_repo_claims" in validation_focus and "MVP did not perform a full live GitHub scan" in output:
        score += 0.05
        reasons.append("Avoids pretending full verification.")
    approval = requires_write_approval(task)
    if approval:
        reasons.append("Write-like task detected; approval required before mutation.")

    sources = observed_sources(observations)
    evidence = _grade_evidence(
        ROUTE_EVALUATORS.get(route_name or ""), output, sources, evidence_base
    )
    reasons.extend(evidence.reasons)
    missing.extend(EVIDENCE_PROSE[code] for code in evidence.gaps)
    if evidence.blocking_note:
        missing.append(evidence.blocking_note)

    # Formatting alone can no longer carry a route that owes evidence. This is
    # the P1 rule: a well-formatted but unsupported answer does not pass.
    score *= evidence.factor
    passed = score >= PASS_THRESHOLD and not approval and not evidence.gaps

    # Retry only when the next pass can actually act on something: a gap the
    # executor knows how to close. Re-running a deterministic executor with
    # identical input cannot improve anything, so never burn an iteration on it.
    actionable = bool(gaps) or evidence.actionable
    should_retry = (not passed) and (iteration < max_iterations) and not approval and actionable
    return AtlasEvaluation(
        quality_score=round(min(score, 1.0), 2),
        passed=passed,
        reasons=reasons,
        missing=missing,
        missing_sections=gaps,
        requires_user_approval=approval,
        should_retry=should_retry,
        suggested_adjustment=(
            _adjustment(gaps, evidence, sources, evidence_base) if should_retry else None
        ),
        evidence_gaps=evidence.gaps,
        unverified_claims=evidence.unverified,
        evidence_coverage=evidence.coverage,
        citation_checks=evidence.citation_checks,
    )


@dataclass(frozen=True)
class _Evidence:
    gaps: list[str]
    unverified: list[str]
    coverage: float | None
    reasons: list[str]
    actionable: bool
    #: Per-finding record of what the deterministic check established, so a
    #: reader can follow a verdict back to a source rather than take the score
    #: on trust. Empty on the citation-only path, which checks nothing.
    citation_checks: list[dict[str, Any]] = field(default_factory=list)
    #: Present when a gap exists that no re-citation can close.
    blocking_note: str | None = None
    # What share of the formatting score survives. A route that owes evidence
    # and shows none keeps 0.75 of it, which lands below PASS_THRESHOLD on its
    # own — the gate is arithmetic, not only a boolean override.
    factor: float = 1.0


def _grade_evidence(
    contract: RouteEvaluator | None,
    output: str,
    sources: list[str],
    base: EvidenceBase | None = None,
) -> _Evidence:
    """Grade support for the claims, or stay silent when the route makes none.

    Two different things can be wrong, and they are not ranked the same. A
    finding that cites nothing is a claim without backing. An output with no
    findings at all is not wrong, but it still has to say which sources it read
    before its review can be taken as grounded in anything.

    Which path runs is decided by what the run carries. A run with an
    `EvidenceBase` gets the deterministic check; a run without one keeps the
    citation-only grading it always had. There is no conversion between them.
    """
    if contract is None:
        return _Evidence(
            gaps=[], unverified=[], coverage=None, reasons=[], actionable=False
        )

    if base is not None:
        return _grade_against_evidence(contract, output, base)

    if contract.requires_sources and not sources:
        # Nothing to cite, so another identical pass cannot fix this. Saying so
        # is more useful than spending the iteration budget to fail again.
        return _Evidence(
            gaps=["no_sources_observed"],
            unverified=[],
            coverage=None,
            reasons=[],
            actionable=False,
            factor=_EVIDENCE_FLOOR,
        )

    findings = findings_in(output, contract.finding_headings)
    if findings:
        unverified = [f for f in findings if not cites_a_source(f, sources)]
        coverage = round((len(findings) - len(unverified)) / len(findings), 2)
        if coverage < contract.min_coverage:
            return _Evidence(
                gaps=["uncited_findings"],
                unverified=unverified,
                coverage=coverage,
                reasons=[],
                actionable=True,
                factor=_coverage_factor(coverage),
            )
        return _Evidence(
            gaps=[],
            unverified=[],
            coverage=coverage,
            reasons=[
                f"All {len(findings)} finding(s) name an observed source. "
                "Citation only: the source was read, the claim is not checked "
                "against its contents."
            ],
            actionable=False,
        )

    if contract.evidence_heading not in output:
        return _Evidence(
            gaps=["sources_not_documented"],
            unverified=[],
            coverage=None,
            reasons=[],
            actionable=True,
            factor=_EVIDENCE_FLOOR,
        )

    # Nothing claimed, so there is nothing to cover. coverage stays None rather
    # than 1.0: a review that asserts no finding has not verified anything.
    return _Evidence(
        gaps=[],
        unverified=[],
        coverage=None,
        reasons=["Output records the sources it read and asserts no finding of its own."],
        actionable=False,
    )


def _grade_against_evidence(
    contract: RouteEvaluator, output: str, base: EvidenceBase
) -> _Evidence:
    """Grade findings against observations that can actually be re-read.

    The gate is citation *integrity*, not truth. A finding that survives it has
    earned the right to be checked semantically, which nothing here does — so
    the reasons say "eligible", never "verified".
    """
    if base.is_empty():
        return _Evidence(
            gaps=["no_sources_observed"],
            unverified=[],
            coverage=None,
            reasons=[],
            actionable=False,
            factor=_EVIDENCE_FLOOR,
        )

    parsed = structured_findings(output)
    if parsed.malformed:
        return _Evidence(
            gaps=["malformed_findings"],
            unverified=[],
            coverage=None,
            reasons=[],
            actionable=True,
            factor=_EVIDENCE_FLOOR,
        )

    # Prose and structure are matched, not derived from one another. A bullet
    # with no matching claim is a finding nobody can check, which is exactly
    # the case that used to pass on a filename appearing in the text.
    prose = findings_in(output, contract.finding_headings)
    claims = parsed.claims()
    uncheckable = [bullet for bullet in prose if bullet not in claims]

    checks = [
        (finding, check_finding(finding, base.observations, base.root))
        for finding in parsed.findings
    ]
    unsound = [(finding, check) for finding, check in checks if not check.citations_are_sound()]

    if not checks and not uncheckable:
        if contract.evidence_heading not in output:
            return _Evidence(
                gaps=["sources_not_documented"],
                unverified=[],
                coverage=None,
                reasons=[],
                actionable=True,
                factor=_EVIDENCE_FLOOR,
            )
        return _Evidence(
            gaps=[],
            unverified=[],
            coverage=None,
            reasons=[
                f"{len(base.observations)} verifiable source(s) were held and the "
                "output asserts no finding of its own."
            ],
            actionable=False,
            citation_checks=[],
        )

    records = [_citation_record(finding, check) for finding, check in checks]
    considered = len(checks) + len(uncheckable)
    sound = considered - len(unsound) - len(uncheckable)
    coverage = round(sound / considered, 2)

    gaps: list[str] = []
    unverified: list[str] = []
    if uncheckable:
        gaps.append("uncheckable_findings")
        unverified.extend(uncheckable)
    if unsound:
        gaps.append("unsound_citations")
        unverified.extend(finding.claim for finding, _ in unsound)

    if gaps:
        blocking = _blocking_statuses(unsound)
        return _Evidence(
            gaps=gaps,
            unverified=unverified,
            coverage=coverage,
            reasons=[],
            actionable=_is_requotable(uncheckable, unsound),
            citation_checks=records,
            factor=_coverage_factor(coverage),
            # Why no retry is offered, in the run itself. "The loop gave up"
            # and "this needs a fresh observation" call for different actions
            # from whoever reads the result.
            blocking_note=(
                "No retry: "
                + ", ".join(sorted({status.value for status in blocking}))
                + " cannot be repaired by re-citing; the sources must be observed again."
                if blocking
                else None
            ),
        )

    return _Evidence(
        gaps=[],
        unverified=[],
        coverage=coverage,
        reasons=[
            f"All {len(checks)} finding(s) cite a source that was read this run, "
            "with a digest, excerpt and line range that still hold. Citation "
            "integrity only: each claim is eligible for semantic verification, "
            "which this run did not perform."
        ],
        actionable=False,
        citation_checks=records,
    )


def _is_requotable(
    uncheckable: list[str], unsound: list[tuple[Finding, Any]]
) -> bool:
    """Whether another pass could close **every** gap without new observations.

    One blocking status decides the answer for the whole output. A retry is a
    single re-run of the producer, so a pass that could fix the citable
    findings would still come back with the stale one unchanged, and the run
    would have spent an iteration to fail on the same ground. Treating the
    fixable half as permission to retry is what made that happen: the earlier
    version returned True as soon as any finding lacked a citation, without
    looking at what the other findings' statuses required.
    """
    if _blocking_statuses(unsound):
        return False
    # A missing citation can be written from sources the run already holds.
    return bool(uncheckable) or bool(unsound)


def _blocking_statuses(unsound: list[tuple[Finding, Any]]) -> list[EvidenceStatus]:
    """Failures no re-wording can repair; they need a fresh observation."""
    return [
        status
        for _, check in unsound
        for _, status in check.statuses
        if status is not EvidenceStatus.INTACT and status not in _REQUOTABLE
    ]


def _citation_record(finding: Finding, check: Any) -> dict[str, Any]:
    return {
        "finding_id": finding.finding_id,
        "claim": finding.claim,
        "verdict": check.verdict,
        "citations_are_sound": check.citations_are_sound(),
        "statuses": [
            {"source_id": source_id, "status": status.value}
            for source_id, status in check.statuses
        ],
    }


_EVIDENCE_FLOOR = 0.75


def _coverage_factor(coverage: float) -> float:
    """Evidence owns the top quarter of the score for routes that require it."""
    return _EVIDENCE_FLOOR + (1.0 - _EVIDENCE_FLOOR) * coverage


def _adjustment(
    gaps: list[str],
    evidence: _Evidence,
    sources: list[str],
    base: EvidenceBase | None = None,
) -> str:
    """What the next pass would have to change. Named concretely or not at all.

    A retry is only worth an iteration if the producer can tell what to fix, so
    this names the failing citation and its status rather than repeating the
    gap code the evaluator already returned.
    """
    parts: list[str] = []
    if gaps:
        parts.append("Add the missing sections: " + ", ".join(gaps) + ".")

    if "uncheckable_findings" in evidence.gaps:
        available = ", ".join(base.source_ids()) if base else ""
        parts.append(
            f"Give every finding an `{FINDINGS_FENCE}` block with a citation naming "
            f"a source_id read this run" + (f"; available: {available}." if available else ".")
        )
    if "malformed_findings" in evidence.gaps:
        parts.append(f"Repair the `{FINDINGS_FENCE}` block so it parses as a list of findings.")
    broken = [
        f"{record['claim'][:60]}: "
        + ", ".join(
            entry["status"] for entry in record["statuses"] if entry["status"] != "intact"
        )
        for record in evidence.citation_checks
        if not record["citations_are_sound"]
    ]
    if broken:
        parts.append("Re-cite from what was actually read — " + "; ".join(broken) + ".")

    if evidence.gaps and sources and not evidence.citation_checks:
        parts.append(
            "Ground each finding in an observed source; available: "
            + ", ".join(sources)
            + "."
        )
    return " ".join(parts)
