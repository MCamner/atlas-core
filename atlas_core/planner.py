from __future__ import annotations
from .state import AtlasPlan, AtlasRoute

def build_plan(task: str, route: AtlasRoute) -> AtlasPlan:
    validation_focus = {
        "repo_review": ["verified_sources", "p0_p1_p2", "small_pr_slices", "no_unverified_repo_claims"],
        "architecture_decision": ["requirements_fit", "risk_coverage", "tradeoff_quality", "clear_recommendation"],
        "root_cause": ["symptoms_vs_causes", "causal_chain", "actionability", "confidence"],
        "decision_tradeoff": ["options_are_distinct", "tradeoffs_are_real", "recommendation_is_clear"],
        "learning": ["simple_explanation", "no_jargon", "example", "understanding_check"],
        "prompt_improvement": ["clear_router_logic", "failure_modes", "testability", "compactness"],
        "general": ["answers_task", "clarity", "next_step"],
    }.get(route.name, ["answers_task", "clarity"])
    return AtlasPlan(
        goal=task,
        route_name=route.name,
        steps=route.steps,
        stop_conditions=[
            "answer_is_actionable",
            "quality_score_above_threshold",
            "max_iterations_reached",
            "write_action_requires_user_approval",
        ],
        validation_focus=validation_focus,
    )
