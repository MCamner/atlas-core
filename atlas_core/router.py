"""Which kind of task this is, from the words in it.

Keyword scoring, and narrow on purpose — there is no model here. What P1.1
box five added is one join: the plan's topic vocabulary is consulted when
nothing else matches, because the two lists were independent and a task could
name a topic `review_plan` knows while landing on a route that builds no plan.
`granska CI-workflow och release-gate` selected `general`, so the run read
nothing, while `build_review_plan` on the same string returned topic `ci`. The
topic was computed and thrown away. See `docs/pinned-repo-review.md`.
"""

from __future__ import annotations
from .review_plan import detect_topic
from .state import AtlasRoute

#: Words that ask for something to be *examined*, as opposed to explained,
#: compared or decided. Deliberately small: this only breaks a tie where no
#: route matched at all, and a longer list would start taking tasks away from
#: routes that did match.
REVIEW_VERBS: tuple[str, ...] = (
    "granska", "review", "revidera", "gå igenom", "ga igenom", "audit",
    "kontrollera", "inspektera", "check",
)

ROUTES: dict[str, dict] = {
    "repo_review": {
        "keywords": ["repo", "repository", "github", "kodbas", "granska repo", "förbättringar", "p0", "p1", "p2", "docs-gap"],
        "steps": ["observe_repo", "summarize", "find_gaps", "prioritize", "recommend_pr_slices"],
        "risk_level": "medium",
    },
    "architecture_decision": {
        "keywords": ["arkitektur", "målarkitektur", "zero trust", "hybrid", "plattform", "integration", "risk", "ai-assistent"],
        "steps": ["requirements", "high_level_design", "risk_review", "options_analysis", "recommendation"],
        "risk_level": "high",
    },
    "root_cause": {
        "keywords": ["grundorsak", "root cause", "varför", "fastnar", "fel", "incident", "problem", "återkommer"],
        "steps": ["problem", "symptoms_vs_causes", "causal_chain", "root_cause", "actions"],
        "risk_level": "medium",
    },
    "decision_tradeoff": {
        "keywords": ["jämför", "beslut", "trade-off", "alternativ", "ska jag", "vilken väg", "rekommendera"],
        "steps": ["context", "options", "tradeoffs", "recommendation", "next_step"],
        "risk_level": "medium",
    },
    "learning": {
        "keywords": ["förklara", "lär mig", "som nybörjare", "feynman", "vad betyder", "hur funkar"],
        "steps": ["simple_explanation", "common_confusion", "example", "understanding_check"],
        "risk_level": "low",
    },
    "prompt_improvement": {
        "keywords": ["prompt", "förbättra prompt", "router", "skill", "system prompt", "atlas"],
        "steps": ["diagnose_prompt", "identify_failure_modes", "rewrite_structure", "test_cases"],
        "risk_level": "low",
    },
    "general": {
        "keywords": [],
        "steps": ["understand", "answer", "next_step"],
        "risk_level": "low",
    },
}

def select_route(task: str) -> AtlasRoute:
    text = task.lower()
    weak = False
    scores: list[tuple[str, int]] = []
    for name, spec in ROUTES.items():
        score = sum(1 for keyword in spec["keywords"] if keyword in text)
        scores.append((name, score))
    scores.sort(key=lambda item: item[1], reverse=True)
    best_name, best_score = scores[0]
    reason = f"Valde route '{best_name}' baserat på {best_score} matchande signal(er)."
    if best_score == 0:
        # Only here. A route that matched keeps what it matched on: a task that
        # asks *why the tests keep failing* is a root cause question whose words
        # happen to include "test", and taking it for a repo review because the
        # topic vocabulary recognised that word would be the same mistake in the
        # other direction. This fires exactly where the old code produced
        # `general` and read nothing.
        topic = detect_topic(task)
        if topic is not None and any(verb in text for verb in REVIEW_VERBS):
            best_name = "repo_review"
            # Lower than any keyword match, because there was none. The route
            # was chosen on two weaker signals agreeing, and the number says so.
            weak = True
            reason = (
                f"Inget nyckelord matchade någon route, men uppgiften ber om en "
                f"granskning och avgränsar till ämnet '{topic.code}'."
            )
        else:
            best_name = "general"
    spec = ROUTES[best_name]
    if weak:
        confidence = 0.5
    else:
        confidence = (
            min(0.95, 0.55 + (best_score * 0.12)) if best_name != "general" else 0.5
        )
    return AtlasRoute(
        name=best_name,
        confidence=confidence,
        reason=reason,
        steps=list(spec["steps"]),
        risk_level=spec["risk_level"],
    )

def list_routes() -> dict[str, dict]:
    return ROUTES
