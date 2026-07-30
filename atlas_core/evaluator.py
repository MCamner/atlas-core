from __future__ import annotations
from .state import AtlasEvaluation
from .safety import requires_write_approval

def evaluate(task: str, output: str, validation_focus: list[str], iteration: int, max_iterations: int) -> AtlasEvaluation:
    reasons: list[str] = []
    missing: list[str] = []
    score = 0.45
    if len(output.strip()) > 300:
        score += 0.15
        reasons.append("Output has enough substance.")
    else:
        missing.append("Output may be too short.")
    if "## Recommendation" in output or "## Recommended" in output or "## Rekommendation" in output:
        score += 0.15
        reasons.append("Contains recommendation.")
    else:
        missing.append("No clear recommendation section.")
    if "## Next step" in output or "## Recommended next step" in output:
        score += 0.10
        reasons.append("Contains next step.")
    else:
        missing.append("No clear next step.")
    if "Confidence" in output or "Konfidens" in output:
        score += 0.05
        reasons.append("Contains confidence.")
    elif "confidence" in validation_focus:
        missing.append("Confidence is missing.")
    if "no_unverified_repo_claims" in validation_focus and "MVP did not perform a full live GitHub scan" in output:
        score += 0.05
        reasons.append("Avoids pretending full verification.")
    approval = requires_write_approval(task)
    if approval:
        reasons.append("Write-like task detected; approval required before mutation.")
    passed = score >= 0.78 and not approval
    should_retry = (not passed) and (iteration < max_iterations) and not approval
    return AtlasEvaluation(
        quality_score=round(min(score, 1.0), 2),
        passed=passed,
        reasons=reasons,
        missing=missing,
        requires_user_approval=approval,
        should_retry=should_retry,
        suggested_adjustment="Add clearer recommendation, next step, or confidence." if should_retry else None,
    )
