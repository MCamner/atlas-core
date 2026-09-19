from __future__ import annotations
from .state import AtlasEvaluation, AtlasPlan
from .evidence import observed_sources

MAX_SOURCES = 8


def execute_plan(
    task: str,
    plan: AtlasPlan,
    observations: list[str] | None = None,
    feedback: AtlasEvaluation | None = None,
) -> str:
    """Render the route body, then the observations it was given, then any
    sections a previous evaluation found missing."""
    observations = observations or []
    build = _ROUTE_BODIES.get(plan.route_name, _general)
    output = build(task)
    if observations:
        output += _sources_section(observations)
    if feedback is not None:
        output += _refinement_section(plan, feedback, observations)
    return output


def _sources_section(observations: list[str]) -> str:
    body = "\n".join(f"- {obs}" for obs in observations[:MAX_SOURCES])
    return f"\n## Sources inspected\n{body}\n"


def _refinement_section(
    plan: AtlasPlan, feedback: AtlasEvaluation, observations: list[str]
) -> str:
    """Close the gaps the evaluator named. Claims nothing when there are none."""
    gaps = [code for code in feedback.missing_sections if code in _GAP_BUILDERS]
    evidence = _evidence_section(feedback, observations)
    if not gaps:
        return evidence
    note = (
        "\n## Loop improvement\n"
        f"Nytt varv efter evaluation. Evalueringen saknade: {', '.join(gaps)}. "
        "Sektionerna nedan lades till i detta varv och är härledda från route-planen, "
        "inte från nya observationer.\n"
    )
    return evidence + note + "".join(_GAP_BUILDERS[code](plan) for code in gaps)


def _evidence_section(feedback: AtlasEvaluation, observations: list[str]) -> str:
    """State what was actually read, and nothing beyond it.

    The deterministic executor cannot confirm the template's claims about a
    repository. What it can do honestly is report which sources it held this
    run, cited by name, and move any claim it could not tie to one into an
    explicitly unverified list. That is the P1 separation of verified findings
    from hypotheses, not a verification of the hypotheses.
    """
    if not any(code in _EVIDENCE_GAPS for code in feedback.evidence_gaps):
        return ""
    sources = observed_sources(observations)
    if not sources:
        return ""

    lines = [
        f"- `{source}` — observerad denna körning; innehållet återges under "
        "'Sources inspected'."
        for source in sources[:MAX_SOURCES]
    ]
    section = "\n## Verified findings\n" + "\n".join(lines) + "\n"
    if feedback.unverified_claims:
        claims = "\n".join(f"- {claim}" for claim in feedback.unverified_claims)
        section += (
            "\n## Unverified claims\n"
            "Följande påståenden kunde inte knytas till någon observerad källa "
            "och står kvar som hypoteser:\n" + claims + "\n"
        )
    return section


_EVIDENCE_GAPS = ("no_findings_cited", "uncited_findings")


def _gap_recommendation(plan: AtlasPlan) -> str:
    steps = ", ".join(plan.steps) if plan.steps else "route-stegen"
    return (
        f"\n## Recommendation\nFölj route '{plan.route_name}' steg för steg: {steps}. "
        f"Stanna när något av stop conditions är uppfyllt: {', '.join(plan.stop_conditions)}.\n"
    )


def _gap_next_step(plan: AtlasPlan) -> str:
    first = plan.steps[0] if plan.steps else "understand"
    return f"\n## Next step\nBörja med steget '{first}'.\n"


def _gap_confidence(plan: AtlasPlan) -> str:
    return (
        "\n## Confidence\nLow. Innehållet i detta varv är härlett från route-planen, "
        "inte från nya observationer eller verifierade källor.\n"
    )


_GAP_BUILDERS = {
    "recommendation": _gap_recommendation,
    "next_step": _gap_next_step,
    "confidence": _gap_confidence,
}

def _repo_review(task: str) -> str:
    return f"""# Repo Review\n\n## Goal\n{task}\n\n## Review method\n- Repoet bör bedömas utifrån roll, boundaries, docs, tester, public-safe-regler och nästa minsta PR-slice.\n- Live kodsanning ska inte gissas. Den måste verifieras i repo, CI eller relevanta verktyg.\n- Förbättringar bör delas i P0/P1/P2 så att arbetet inte blir en stor blandad PR.\n\n## P0 — fixa först\n- Bekräfta repoets read-order och source-of-truth boundary.\n- Identifiera stale docs eller instruktioner som kan få agenten att läsa för mycket.\n- Lägg till eller uppdatera validation commands om de saknas.\n\n## P1 — fixa sedan\n- Förbättra exempel, screenshots eller demo-output där det hjälper repoets publika förståelse.\n- Lägg till tydligare issue/PR-mallar om repoet saknar styrning.\n- Dela övervuxna docs i små context surfaces.\n\n## P2 — polish\n- Gör README kortare om den duplicerar djupare docs.\n- Lägg till mer kompakta testprompter för Codex/Claude/ChatGPT.\n- Skapa en liten roadmap med nästa 3 PR-slices.\n\n## Suggested PR slices\n1. docs: tighten read-order and truth-boundary section\n2. tests: add/verify context budget and public-safe validation\n3. examples: add one sanitized end-to-end context-pack example\n\n## Recommendation\nTa P0-listan först och kör varje post som en egen PR-slice. Blanda inte in P1 eller P2 i samma diff.\n\n## Next step\nVerifiera P0-listan mot repots faktiska innehåll innan någon ändring görs.\n\n## Confidence\nMedium. This MVP did not perform a full live GitHub scan unless observations were provided by an adapter.\n"""

def _architecture_decision(task: str) -> str:
    return f"""# Architecture Decision\n\n## Goal\n{task}\n\n## Requirements\n- Säker styrning\n- Tydliga trust boundaries\n- Stegvis införande\n- Mätbar kvalitet och kostnad\n- Möjlighet att byta komponenter senare\n\n## High-level design\nBygg runt ett kontrollplan: identitet, policy, gateway, observability och tydlig datagräns.\nLåt implementationer/modeller vara utbytbara bakom stabila kontrakt.\n\n## Risks\n- För brett scope i första versionen\n- Oklara informationsklasser\n- Leverantörslåsning\n- Otillräcklig logging eller för innehållsrik logging\n- Ingen exit-plan\n\n## Options\n1. Köp färdig tjänst — snabbast, men mest låsning.\n2. Bygg själv — mest kontroll, men dyrast och långsammast.\n3. Hybrid — bäst balans när säkerhet och snabb nytta båda spelar roll.\n\n## Recommendation\nVälj hybrid som default om kraven innehåller både snabb införing och stark kontroll.\n\n## Next step\nDefiniera en 6–12 veckors pilot med tydliga go/no-go-kriterier.\n\n## Confidence\nMedium. Faktiska krav, juridik och produktdetaljer måste verifieras.\n"""

def _root_cause(task: str) -> str:
    return f"""# Root Cause Analysis\n\n## Problem\n{task}\n\n## Symptoms vs causes\n- Symptom: det synliga problemet eller upprepade stoppet.\n- Contributing factors: process, verktyg, otydligt ägarskap eller sena kontroller.\n- Possible root cause: systemet saknar tidig feedback, tydliga gates eller ansvar.\n\n## Causal chain\nTrigger\n↓\nSen upptäckt / otydlig signal\n↓\nManuell tolkning eller brist på ansvar\n↓\nFlödet fastnar i sista steget\n\n## Likely root cause\nKontrollerna kommer för sent eller är för otydliga för att teamet ska kunna agera tidigare.\n\n## Leverage points\n- Flytta kontroller tidigare.\n- Gör stoppsignaler maskinläsbara.\n- Definiera ägare för varje gate.\n- Mät återkommande stopporsaker.\n\n## Recommended actions\n1. Logga de senaste 5 stopporsakerna.\n2. Dela dem i policy, test, review, release eller ägarskap.\n3. Flytta vanligaste stoppet till tidigare fas.\n4. Skapa en enkel check innan sista steget.\n\n## Next step\nBörja med punkt 1: logga de senaste 5 stopporsakerna innan någon process ändras.\n\n## Confidence\nMedium without concrete incident data.\n"""

def _decision_tradeoff(task: str) -> str:
    return f"""# Decision & Trade-off\n\n## Decision\n{task}\n\n## Options\n1. Minimal path — snabbt, låg risk, men begränsad effekt.\n2. Balanced path — lagom scope, tydlig kvalitet, bra för nästa steg.\n3. Ambitious path — hög effekt, men större komplexitet och risk.\n\n## Trade-offs\n- Speed vs control\n- Simplicity vs flexibility\n- Short-term delivery vs long-term maintainability\n- Manual work vs automation\n\n## Recommendation\nVälj balanced path om beslutet påverkar fler än ett arbetsflöde eller repo.\n\n## Next step\nSkriv ned beslutets success criteria innan implementation.\n\n## Confidence\nMedium.\n"""

def _learning(task: str) -> str:
    return f"""# Explanation\n\n## Simple explanation\n{task}\n\nTänk på det som ett system där du först vill förstå vad saken gör, sedan varför den finns, och till sist hur du kan använda den utan att blanda ihop den med andra saker.\n\n## Common confusion\nMånga blandar ihop verktyget, processen, minnet och resultatet. Separera dessa så blir systemet lättare att förstå.\n\n## Example\nOm Atlas är en loop, är prompten inte motorn. Prompten är mer som instruktionen på instrumentpanelen.\n\n## Understanding check\nKan du beskriva skillnaden mellan en router och en executor i en mening?\n\n## Recommendation\nBygg förståelsen i den ordningen: vad saken gör, varför den finns, hur den används. Hoppa inte till detaljerna först.\n\n## Next step\nSvara på understanding check ovan med egna ord innan du går vidare.\n\n## Confidence\nMedium.\n"""

def _prompt_improvement(task: str) -> str:
    return f"""# Prompt Improvement\n\n## Goal\n{task}\n\n## Diagnosis\nEn stark prompt ska inte försöka bära hela systemet själv. Den ska definiera roll, gränser, route-regler, output och quality gates.\n\n## Failure modes\n- För lång prompt som blandar policy, minne och output.\n- Router som väljer prompt men inte kör svaret.\n- Otydliga stop-regler.\n- Inga testfall.\n\n## Better structure\n1. Trigger\n2. Task classification\n3. Route selection\n4. Execution rule\n5. Evaluation rule\n6. Output format\n7. Safety/write boundary\n8. Test cases\n\n## Recommendation\nGör prompten till ett tunt gränssnitt ovanpå en loop/state-machine.\n\n## Next step\nSkriv routes som data, inte som långa promptstycken.\n\n## Confidence\nHigh.\n"""

def _general(task: str) -> str:
    return f"""# Answer\n\n## Goal\n{task}\n\n## Response\nAtlas Core hanterar detta som en generell uppgift. För ett starkare svar, ge mer kontext eller välj en specifik route.\n\n## Recommendation\nAnvänd en specifik route om uppgiften är större än en enkel fråga.\n\n## Next step\nKör igen med mer konkret mål, constraints och önskat format.\n\n## Confidence\nLow-to-medium.\n"""


_ROUTE_BODIES = {
    "repo_review": _repo_review,
    "architecture_decision": _architecture_decision,
    "root_cause": _root_cause,
    "decision_tradeoff": _decision_tradeoff,
    "learning": _learning,
    "prompt_improvement": _prompt_improvement,
    "general": _general,
}
