"""What a run intends to do, and — for a review — what it is asking.

The validation focus and step list are per route and have been since 1.0. What
P1.1 adds is `review`: a route that reviews a repository now carries the
question it is asking and the sources that question needs, bound to one
snapshot. See `atlas_core/review_plan.py` for why those are patterns rather
than paths.
"""

from __future__ import annotations
from .review_plan import ReviewPlan, build_review_plan, detect_topic
from .state import AtlasPlan, AtlasRoute

#: Routes that review a repository, and therefore ask a question of it. A route
#: without an entry here has a goal and no question, and carries no review plan
#: rather than an empty one.
REVIEWING_ROUTES: frozenset[str] = frozenset({"repo_review"})


def build_plan(
    task: str, route: AtlasRoute, snapshot_id: str | None = None
) -> AtlasPlan:
    validation_focus = {
        "repo_review": ["verified_sources", "p0_p1_p2", "small_pr_slices", "no_unverified_repo_claims"],
        "architecture_decision": ["requirements_fit", "risk_coverage", "tradeoff_quality", "clear_recommendation"],
        "root_cause": ["symptoms_vs_causes", "causal_chain", "actionability", "confidence"],
        "decision_tradeoff": ["options_are_distinct", "tradeoffs_are_real", "recommendation_is_clear"],
        "learning": ["simple_explanation", "no_jargon", "example", "understanding_check"],
        "prompt_improvement": ["clear_router_logic", "failure_modes", "testability", "compactness"],
        "general": ["answers_task", "clarity", "next_step"],
    }.get(route.name, ["answers_task", "clarity"])
    review: ReviewPlan | None = None
    if route.name in REVIEWING_ROUTES and snapshot_id:
        # Only with a snapshot. A review plan that could not name the state it
        # is about would be a question with no subject, and `ReviewPlan`
        # refuses to be built that way.
        review = build_review_plan(task, snapshot_id)

    unused_topic: dict[str, str] | None = None
    if review is None:
        # The task may still narrow. Saying so costs nothing and stops the run
        # from looking as though there was no question to ask.
        topic = detect_topic(task)
        if topic is not None:
            unused_topic = {
                "topic": topic.code,
                "question": topic.question,
                "reason": (
                    "route_has_no_review_contract"
                    if route.name not in REVIEWING_ROUTES
                    else "no_snapshot"
                ),
            }

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
        review=review,
        unused_topic=unused_topic,
    )
