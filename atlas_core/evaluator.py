from __future__ import annotations
from .state import AtlasEvaluation
from .safety import requires_write_approval

PASS_THRESHOLD = 0.78

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


def evaluate(task: str, output: str, validation_focus: list[str], iteration: int, max_iterations: int) -> AtlasEvaluation:
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
    passed = score >= PASS_THRESHOLD and not approval
    # Retry only when the next pass can actually act on something: a gap the
    # executor knows how to close. Re-running a deterministic executor with
    # identical input cannot improve anything, so never burn an iteration on it.
    should_retry = (not passed) and (iteration < max_iterations) and not approval and bool(gaps)
    return AtlasEvaluation(
        quality_score=round(min(score, 1.0), 2),
        passed=passed,
        reasons=reasons,
        missing=missing,
        missing_sections=gaps,
        requires_user_approval=approval,
        should_retry=should_retry,
        suggested_adjustment=("Add the missing sections: " + ", ".join(gaps) + ".") if should_retry else None,
    )
