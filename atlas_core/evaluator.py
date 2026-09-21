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

from .state import AtlasEvaluation, NextAction
from .safety import requires_write_approval
from .evidence_base import EvidenceBase
from .claim_check import ClaimResult, ClaimVerdict, apply_verdict, check_claim
from .finding import EvidenceStatus, Finding, check_finding
from .evidence import (
    FINDINGS_FENCE,
    cites_a_source,
    findings_in,
    observed_sources,
    structured_findings,
)

#: What each route owes before it is done, as (code, requirement) pairs.
#:
#: P1.1 box three asks for explicit exit criteria per task instead of a
#: general score over text length and headings. The old gate was arithmetic:
#: 0.45 to begin with, 0.15 for clearing three hundred characters, a little
#: per heading, times an evidence factor, against a threshold. Nothing in it
#: said what the route owed, and an answer could clear the bar with a declared
#: section missing — a run reporting that it had met its gate while one of its
#: own requirements went unmet.
#:
#: Every criterion listed must be met. There is no weighting, because a
#: requirement that can be outvoted by other requirements is not one.
EXIT_CRITERIA: dict[str, tuple[tuple[str, str], ...]] = {
    "repo_review": (
        (
            "sources_documented",
            "The output records which sources it read, so a reader can tell what "
            "the review rests on.",
        ),
        (
            "findings_are_checkable",
            "Every finding carries a machine-readable citation naming a source "
            "this run read.",
        ),
        (
            "citations_hold",
            "Every citation still points at the lines it claims, in a source "
            "that has not moved.",
        ),
        (
            "claims_are_settled",
            "Every finding is stated so it can be decided, and was decided in "
            "its favour against observed lines.",
        ),
        ("recommendation", "The output states a recommendation."),
        ("next_step", "The output states a next step."),
        ("confidence", "The output states how confident it is."),
    ),
    # Length stays here and nowhere else. A route that checks nothing against a
    # source has only the shape of an answer to go on, so the proxy remains —
    # named, and visible in the run document, rather than folded into a sum.
    # A route that does check its claims does not need it: a short review whose
    # findings were settled against observed lines is done, and words are not
    # what makes it so.
    "__generic__": (
        ("substance", "The output is long enough to be an answer rather than a stub."),
        ("recommendation", "The output states a recommendation."),
        ("next_step", "The output states a next step."),
        ("confidence", "The output states how confident it is."),
    ),
}

#: Which criterion an evidence gap fails. The gap codes are unchanged; this
#: says what each one means for being done.
_CRITERION_FOR_GAP: dict[str, tuple[str, ...]] = {
    "no_sources_observed": ("sources_documented",),
    "sources_not_documented": ("sources_documented",),
    "uncited_findings": ("findings_are_checkable",),
    "uncheckable_findings": ("findings_are_checkable",),
    "malformed_findings": ("findings_are_checkable",),
    "unsound_citations": ("citations_hold",),
    "contradicted_findings": ("claims_are_settled",),
    "unverified_findings": ("claims_are_settled",),
    "claim_text_mismatch": ("claims_are_settled",),
    # All three, because on this path none of them was evaluated at all. A
    # criterion reported met while no deterministic check ran is the run
    # document asserting something nobody established, which is the failure
    # this whole phase exists to remove.
    "claims_not_checked": (
        "claims_are_settled",
        "citations_hold",
        "findings_are_checkable",
    ),
}

#: The shortest output that is an answer rather than a stub. A proxy, and
#: named as one — see `EXIT_CRITERIA["__generic__"]`.
MIN_SUBSTANCE = 300


def criteria_for(route_name: str | None) -> tuple[tuple[str, str], ...]:
    """The criteria a route must meet. Generic ones when it declares none."""
    return EXIT_CRITERIA.get(route_name or "", EXIT_CRITERIA["__generic__"])


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
    # Whether a sound citation is enough. When true, a finding must also name
    # a condition that would refute it, and that condition must survive. A
    # route that only summarises has nothing to refute and leaves this off.
    requires_claim_check: bool = False


# Per P1, read-only repository review comes first. A route with no entry here
# is graded on formatting alone, exactly as it was before.
ROUTE_EVALUATORS: dict[str, RouteEvaluator] = {
    "repo_review": RouteEvaluator(
        evidence_heading="## Observed sources",
        # "## Findings" first: a heading is not a verification, and one that
        # calls its contents verified asserts exactly what the run has to
        # establish. "## Verified findings" stays accepted so existing
        # producers keep working, and the claim ledger in the rendered text
        # says per claim which of them was actually settled.
        finding_headings=("## Findings", "## Verified findings"),
        requires_sources=True,
        requires_claim_check=True,
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
    "claims_not_checked": (
        "Findings name a source that was read, and nothing compared them "
        "against it. Naming a file is not evidence about what the file says, "
        "so no claim here is established — whether or not it happens to be "
        "true. Collect observations and run with an evidence base."
    ),
    "unsound_citations": (
        "Some findings cite a source that does not hold up: unknown id, a "
        "digest or quote that does not match, or a source that has moved."
    ),
    "contradicted_findings": (
        "Some findings are refuted by the source they cite: they named a "
        "condition that would make them false, and it is false."
    ),
    "unverified_findings": (
        "Some findings are stated as free text, so their truth was not "
        "established. A settled condition beside a free-text claim says the "
        "producer's own test passed, not that the claim holds."
    ),
    "claim_text_mismatch": (
        "Some findings say something other than what their typed claim says, "
        "so the sentence a reader sees is not the sentence that was settled."
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

    criteria = criteria_for(route_name)
    declared = {code for code, _ in criteria}
    unmet: set[str] = set()

    if "substance" in declared and len(output.strip()) <= MIN_SUBSTANCE:
        unmet.add("substance")
        missing.append("Output may be too short.")
    elif "substance" in declared:
        reasons.append("Output has enough substance.")

    gaps = missing_sections(output)
    for code in REQUIRED_SECTIONS:
        if code not in declared:
            continue
        if code in gaps:
            unmet.add(code)
            missing.append(SECTION_PROSE[code])
        else:
            reasons.append(SECTION_PRESENT[code])

    if "no_unverified_repo_claims" in validation_focus and "MVP did not perform a full live GitHub scan" in output:
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

    # Every gap the evidence check found fails the criterion it belongs to. The
    # codes are unchanged; what is new is that each one names a requirement
    # rather than costing a fraction of a score.
    for gap in evidence.gaps:
        unmet.update(_CRITERION_FOR_GAP.get(gap, ("claims_are_settled",)))
    unmet &= declared

    met = sorted(declared - unmet)
    # A report, not a gate. It says how much of what the route owed was
    # delivered; `passed` is decided by whether anything is outstanding.
    score = round(len(met) / len(declared), 2) if declared else 1.0
    passed = not unmet and not approval

    # Retry only when the next pass can actually act on something: a gap the
    # executor knows how to close. Re-running a deterministic executor with
    # identical input cannot improve anything, so never burn an iteration on it.
    # Formatting cannot repair a missing or stale source.
    actionable = evidence.actionable if evidence.gaps else bool(gaps)
    # Split deliberately: what could still be tried, and what will be tried.
    # A run that stops with something actionable left stopped because of its
    # bound; one that stops with nothing left had nowhere to go. They are
    # different stop reasons, and folding the budget into a single boolean
    # made them indistinguishable.
    retry_is_possible = (not passed) and not approval and actionable
    should_retry = retry_is_possible and iteration < max_iterations
    return AtlasEvaluation(
        quality_score=score,
        passed=passed,
        met_criteria=met,
        unmet_criteria=sorted(unmet),
        reasons=reasons,
        missing=missing,
        missing_sections=gaps,
        requires_user_approval=approval,
        should_retry=should_retry,
        retry_is_possible=retry_is_possible,
        suggested_adjustment=(
            _adjustment(gaps, evidence, sources, evidence_base) if should_retry else None
        ),
        # Emitted whenever the answer did not clear its gate, including when
        # no retry is offered. A run that stops `blocked` has a next action too
        # — it is simply the host's to take, not the producer's, and saying
        # nothing there would leave the one case that needs a human the least
        # served. Never on a passing run: formatting weights are not a gate, so
        # an answer can pass with a section missing, and telling a caller to act
        # on a run that met its gate is an instruction it did not ask for.
        next_action=(
            _next_action(gaps, evidence, sources, evidence_base)
            if not passed
            else None
        ),
        evidence_gaps=evidence.gaps,
        unverified_claims=evidence.unverified,
        evidence_coverage=evidence.coverage,
        citation_checks=evidence.citation_checks,
        blocked_by=evidence.blocked_by,
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
    #: The same fact as a list of status codes. The note is for a reader; this
    #: is what the controller branches on, so a stop reason never depends on
    #: how a sentence was worded.
    blocked_by: list[str] = field(default_factory=list)


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
                )
        # Every finding names a source that was read, and nothing compared
        # any of them against it. That is not a weaker pass, it is no check:
        # a false claim and a true one are indistinguishable here, and a
        # route that declares `claims_are_settled` has had none of its
        # evidence criteria evaluated. Fail closed.
        #
        # Not actionable. Re-wording cannot produce an evidence base; only the
        # caller can collect observations, so burning an iteration on another
        # identical pass would fail the same way.
        return _Evidence(
            gaps=["claims_not_checked"],
            unverified=list(findings),
            coverage=coverage,
            reasons=[],
            actionable=False,
        )

    if contract.evidence_heading not in output:
        return _Evidence(
            gaps=["sources_not_documented"],
            unverified=[],
            coverage=None,
            reasons=[],
            actionable=True,
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
        )

    parsed = structured_findings(output)
    if parsed.malformed:
        return _Evidence(
            gaps=["malformed_findings"],
            unverified=[],
            coverage=None,
            reasons=[],
            actionable=True,
        )

    # Prose and structure are matched, not derived from one another. A bullet
    # with no matching claim is a finding nobody can check, which is exactly
    # the case that used to pass on a filename appearing in the text.
    prose = findings_in(output, contract.finding_headings)
    claims = parsed.claims()
    uncheckable = [bullet for bullet in prose if bullet not in claims]

    checks = [
        (finding, check_finding(finding, base.observations, base.root, readers=base.readers))
        for finding in parsed.findings
    ]
    unsound = [(finding, check) for finding, check in checks if not check.citations_are_sound()]

    # Only a finding whose citations hold goes on to the semantic step. A
    # refutation resting on a source the finding cannot point at would be an
    # accusation about the wrong file.
    claim_verdicts: dict[str, ClaimVerdict] = {}
    if contract.requires_claim_check:
        for (finding, check), (_, typed, condition) in zip(checks, parsed.entries):
            if check.citations_are_sound():
                claim_verdicts[finding.finding_id] = check_claim(
                    finding, typed, condition, base.observations, base.root, base.readers
                )

    if not checks and not uncheckable:
        if contract.evidence_heading not in output:
            return _Evidence(
                gaps=["sources_not_documented"],
                unverified=[],
                coverage=None,
                reasons=[],
                actionable=True,
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

    records = [
        _citation_record(finding, check, claim_verdicts.get(finding.finding_id))
        for finding, check in checks
    ]

    # Only a decisive result moves a finding. A settled condition, however
    # cleanly settled, is a record of the producer's own test — not of the
    # claim — so it lands in `unchecked` beside a finding that declared nothing.
    refuted = [
        finding
        for finding, _ in checks
        if (verdict := claim_verdicts.get(finding.finding_id)) is not None
        and verdict.result is ClaimResult.CONTRADICTED
    ]
    mismatched = [
        finding
        for finding, _ in checks
        if (verdict := claim_verdicts.get(finding.finding_id)) is not None
        and verdict.result is ClaimResult.CLAIM_TEXT_MISMATCH
    ]
    unchecked = [
        finding
        for finding, check in checks
        if check.citations_are_sound()
        and (verdict := claim_verdicts.get(finding.finding_id)) is not None
        and not verdict.is_decisive()
        and verdict.result is not ClaimResult.CLAIM_TEXT_MISMATCH
    ]

    considered = len(checks) + len(uncheckable)
    supported = (
        considered
        - len(unsound)
        - len(uncheckable)
        - len(refuted)
        - len(mismatched)
        - len(unchecked)
    )
    coverage = round(supported / considered, 2)

    gaps: list[str] = []
    unverified: list[str] = []
    if uncheckable:
        gaps.append("uncheckable_findings")
        unverified.extend(uncheckable)
    if unsound:
        gaps.append("unsound_citations")
        unverified.extend(finding.claim for finding, _ in unsound)
    if refuted:
        gaps.append("contradicted_findings")
        unverified.extend(finding.claim for finding in refuted)
    if mismatched:
        gaps.append("claim_text_mismatch")
        unverified.extend(finding.claim for finding in mismatched)
    if unchecked:
        gaps.append("unverified_findings")
        unverified.extend(finding.claim for finding in unchecked)

    if gaps:
        blocking = _blocking_statuses(unsound)
        return _Evidence(
            blocked_by=sorted({status.value for status in blocking}),
            gaps=gaps,
            unverified=unverified,
            coverage=coverage,
            reasons=[],
            actionable=_is_requotable(
                uncheckable, unsound, refuted, unchecked + mismatched
            ),
            citation_checks=records,
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

    if contract.requires_claim_check:
        reason = (
            f"All {len(checks)} finding(s) cite a source that still holds and are "
            "stated as typed claims, each settled against the lines the run recorded. "
            "The claim is the predicate, so there is no gap between what was asserted "
            "and what was tested."
        )
    else:
        reason = (
            f"All {len(checks)} finding(s) cite a source that was read this run, "
            "with a digest, excerpt and line range that still hold. Citation "
            "integrity only: each claim is eligible for semantic verification, "
            "which this route does not require."
        )
    return _Evidence(
        gaps=[],
        unverified=[],
        coverage=coverage,
        reasons=[reason],
        actionable=False,
        citation_checks=records,
    )


def _is_requotable(
    uncheckable: list[str],
    unsound: list[tuple[Finding, Any]],
    refuted: list[Finding] | None = None,
    unchecked: list[Finding] | None = None,
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
    # A missing citation can be written from sources the run already holds; a
    # missing condition can be declared; a refuted finding can be corrected or
    # dropped. All three are repairs the producer can make without new sources.
    return bool(uncheckable) or bool(unsound) or bool(refuted) or bool(unchecked)


def _blocking_statuses(unsound: list[tuple[Finding, Any]]) -> list[EvidenceStatus]:
    """Failures no re-wording can repair; they need a fresh observation."""
    return [
        status
        for _, check in unsound
        for _, status in check.statuses
        if status is not EvidenceStatus.INTACT and status not in _REQUOTABLE
    ]


def _citation_record(
    finding: Finding, check: Any, claim: ClaimVerdict | None
) -> dict[str, Any]:
    """One finding's full record: the pointer, the claim, and the verdict.

    Each citation carries the span it relied on, not only the id of the source.
    P0.1 asks that a finding be traceable to a `source_id` *and* an exact
    excerpt; an id alone leaves a reader with the name of a file and no way to
    see which lines the claim rests on without re-reading it and guessing. The
    id resolves in the same run's `evidence_manifest`, so both ends of the link
    are in one document.

    The spans come from the finding's own citations, paired with the statuses
    positionally because `check_finding` produces one status per citation in
    order. A length mismatch would silently attach one citation's span to
    another's verdict, which is the kind of quiet misattribution this phase
    exists to prevent, so it raises instead.
    """
    decided = apply_verdict(finding, check, claim) if claim else check.apply_to(finding)
    if len(check.statuses) != len(finding.evidence):
        raise ValueError(
            f"{len(check.statuses)} statuses for {len(finding.evidence)} citations: "
            "a record cannot say which span a verdict belongs to"
        )
    return {
        "finding_id": finding.finding_id,
        "claim": finding.claim,
        "verdict": decided.verdict,
        "verification_method": decided.verification_method,
        # The severity that survived the check, and the one the producer
        # declared. They differ whenever the claim was not established, which
        # is the point: an unestablished finding must not carry a number that
        # reads as an assessment. See `finding.severity_after`.
        "severity": decided.severity,
        "declared_severity": decided.declared_severity,
        "severity_rationale": decided.severity_rationale,
        "citations_are_sound": check.citations_are_sound(),
        "statuses": [
            {
                "source_id": source_id,
                "status": status.value,
                "line_start": ref.line_start,
                "line_end": ref.line_end,
                # Masked on the way out with the rest of the document; a quote
                # is a slice of a real file and can carry what an excerpt can.
                "quoted": ref.quoted,
            }
            for (source_id, status), ref in zip(check.statuses, finding.evidence)
        ],
        "claim_check": claim.to_dict() if claim else None,
    }


def _next_action(
    gaps: list[str],
    evidence: _Evidence,
    sources: list[str],
    base: EvidenceBase | None = None,
) -> NextAction | None:
    """The one thing that has to happen first, as data.

    Chosen by the order in `NEXT_ACTION_KINDS`, which is not severity but
    precedence: a block that cannot be parsed makes every question about an
    individual citation moot, and a source that has moved cannot be re-cited at
    all. `gap_codes` carries everything outstanding, so choosing one action
    hides nothing.

    None when nothing is outstanding. An empty action on a passing run would be
    a next step nobody asked for.
    """
    codes = list(evidence.gaps) + list(gaps)
    if not codes:
        return None

    if "claims_not_checked" in evidence.gaps:
        # Ahead of everything else for the same reason `observe_again` is:
        # nothing a producer can write closes it. The run has no evidence base,
        # so no citation it could offer would be checked against anything.
        return NextAction(
            kind="observe_again",
            gap_codes=codes,
            actor="host",
            details={
                "reason": "no_evidence_base",
                "sources_named": list(sources),
                "requirement": (
                    "Collect Observation.v1 values and pass them as `evidence` "
                    "so the claims can be checked against what was read."
                ),
            },
        )

    if evidence.blocked_by:
        return NextAction(
            kind="observe_again",
            gap_codes=codes,
            actor="host",
            details={
                "blocked_by": list(evidence.blocked_by),
                # The claims resting on what moved, so a host knows what the
                # re-read is for rather than only that one is needed.
                "claims": [
                    record["claim"]
                    for record in evidence.citation_checks
                    if not record["citations_are_sound"]
                ],
            },
        )

    if "malformed_findings" in evidence.gaps:
        return NextAction(
            kind="repair_findings_block",
            gap_codes=codes,
            details={"fence": FINDINGS_FENCE},
        )

    refuted = [
        {
            "claim": record["claim"],
            "reason": (record["claim_check"] or {}).get("reason", ""),
        }
        for record in evidence.citation_checks
        if (record["claim_check"] or {}).get("result") == "contradicted"
    ]
    if refuted:
        return NextAction(
            kind="drop_refuted_claim", gap_codes=codes, details={"claims": refuted}
        )

    expected = [
        str((record["claim_check"] or {}).get("checked", {}).get("expected_claim"))
        for record in evidence.citation_checks
        if (record["claim_check"] or {}).get("result") == "claim_text_mismatch"
    ]
    if expected:
        return NextAction(
            kind="restate_claim", gap_codes=codes, details={"expected_claims": expected}
        )

    broken = [
        {
            "claim": record["claim"],
            "statuses": [
                entry["status"]
                for entry in record["statuses"]
                if entry["status"] != "intact"
            ],
        }
        for record in evidence.citation_checks
        if not record["citations_are_sound"]
    ]
    if broken:
        return NextAction(
            kind="recite_from_source", gap_codes=codes, details={"citations": broken}
        )

    if evidence.gaps:
        return NextAction(
            kind="cite_sources",
            gap_codes=codes,
            details={
                "fence": FINDINGS_FENCE,
                "available_source_ids": base.source_ids() if base else [],
                "available_sources": base.paths() if base else list(sources),
            },
        )

    return NextAction(kind="add_sections", gap_codes=codes, details={"sections": gaps})


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
    refuted = [
        f"{record['claim'][:60]}: {(record['claim_check'] or {}).get('reason', '')}"
        for record in evidence.citation_checks
        if (record["claim_check"] or {}).get("result") == "contradicted"
    ]
    if refuted:
        parts.append("Drop or correct what the source refutes — " + "; ".join(refuted) + ".")

    # The expected sentence, verbatim. A typed claim's text is derived, so
    # telling a producer to "match it" without saying what it is would leave
    # the only fixable part of the failure unstated.
    expected = [
        str((record["claim_check"] or {}).get("checked", {}).get("expected_claim"))
        for record in evidence.citation_checks
        if (record["claim_check"] or {}).get("result") == "claim_text_mismatch"
    ]
    if expected:
        parts.append(
            "State each typed claim exactly as it reads: "
            + "; ".join(repr(text) for text in expected)
            + "."
        )

    if "unverified_findings" in evidence.gaps:
        parts.append(
            "A free-text finding cannot be established. State it as a typed claim "
            "— {\"kind\": \"source_contains_literal\"|\"source_lacks_literal\", "
            "\"source_id\": ..., \"text\": ...} — and write its derived sentence as "
            "the claim, or drop it."
        )
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
