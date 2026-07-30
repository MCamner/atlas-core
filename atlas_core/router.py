from __future__ import annotations
from .state import AtlasRoute

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
    scores: list[tuple[str, int]] = []
    for name, spec in ROUTES.items():
        score = sum(1 for keyword in spec["keywords"] if keyword in text)
        scores.append((name, score))
    scores.sort(key=lambda item: item[1], reverse=True)
    best_name, best_score = scores[0]
    if best_score == 0:
        best_name = "general"
    spec = ROUTES[best_name]
    confidence = min(0.95, 0.55 + (best_score * 0.12)) if best_name != "general" else 0.5
    return AtlasRoute(
        name=best_name,
        confidence=confidence,
        reason=f"Valde route '{best_name}' baserat på {best_score} matchande signal(er).",
        steps=list(spec["steps"]),
        risk_level=spec["risk_level"],
    )

def list_routes() -> dict[str, dict]:
    return ROUTES
