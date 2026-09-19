from __future__ import annotations

from dataclasses import dataclass

from .state import AtlasEvaluation
from .safety import requires_write_approval
from .evidence import cites_a_source, findings_in, observed_sources

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
}

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
    evidence = _grade_evidence(ROUTE_EVALUATORS.get(route_name or ""), output, sources)
    reasons.extend(evidence.reasons)
    missing.extend(EVIDENCE_PROSE[code] for code in evidence.gaps)

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
        suggested_adjustment=_adjustment(gaps, evidence, sources) if should_retry else None,
        evidence_gaps=evidence.gaps,
        unverified_claims=evidence.unverified,
        evidence_coverage=evidence.coverage,
    )


@dataclass(frozen=True)
class _Evidence:
    gaps: list[str]
    unverified: list[str]
    coverage: float | None
    reasons: list[str]
    actionable: bool
    # What share of the formatting score survives. A route that owes evidence
    # and shows none keeps 0.75 of it, which lands below PASS_THRESHOLD on its
    # own — the gate is arithmetic, not only a boolean override.
    factor: float = 1.0


def _grade_evidence(
    contract: RouteEvaluator | None, output: str, sources: list[str]
) -> _Evidence:
    """Grade support for the claims, or stay silent when the route makes none.

    Two different things can be wrong, and they are not ranked the same. A
    finding that cites nothing is a claim without backing. An output with no
    findings at all is not wrong, but it still has to say which sources it read
    before its review can be taken as grounded in anything.
    """
    if contract is None:
        return _Evidence(
            gaps=[], unverified=[], coverage=None, reasons=[], actionable=False
        )

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


_EVIDENCE_FLOOR = 0.75


def _coverage_factor(coverage: float) -> float:
    """Evidence owns the top quarter of the score for routes that require it."""
    return _EVIDENCE_FLOOR + (1.0 - _EVIDENCE_FLOOR) * coverage


def _adjustment(gaps: list[str], evidence: _Evidence, sources: list[str]) -> str:
    parts: list[str] = []
    if gaps:
        parts.append("Add the missing sections: " + ", ".join(gaps) + ".")
    if evidence.gaps and sources:
        parts.append(
            "Ground each finding in an observed source; available: "
            + ", ".join(sources)
            + "."
        )
    return " ".join(parts)
