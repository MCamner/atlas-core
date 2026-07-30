from __future__ import annotations
from .state import AtlasPlan

def execute_plan(task: str, plan: AtlasPlan, observations: list[str] | None = None) -> str:
    observations = observations or []
    if plan.route_name == "repo_review":
        return _repo_review(task, observations)
    if plan.route_name == "architecture_decision":
        return _architecture_decision(task)
    if plan.route_name == "root_cause":
        return _root_cause(task)
    if plan.route_name == "decision_tradeoff":
        return _decision_tradeoff(task)
    if plan.route_name == "learning":
        return _learning(task)
    if plan.route_name == "prompt_improvement":
        return _prompt_improvement(task)
    return _general(task)

def _repo_review(task: str, observations: list[str]) -> str:
    source_note = "\n".join(f"- {obs}" for obs in observations[:8]) if observations else "- Inga externa repo-filer lästa i denna MVP-körning."
    return f"""# Repo Review\n\n## Goal\n{task}\n\n## Sources inspected\n{source_note}\n\n## Key findings\n- Repoet bör bedömas utifrån roll, boundaries, docs, tester, public-safe-regler och nästa minsta PR-slice.\n- Live kodsanning ska inte gissas. Den måste verifieras i repo, CI eller relevanta verktyg.\n- Förbättringar bör delas i P0/P1/P2 så att arbetet inte blir en stor blandad PR.\n\n## P0 — fixa först\n- Bekräfta repoets read-order och source-of-truth boundary.\n- Identifiera stale docs eller instruktioner som kan få agenten att läsa för mycket.\n- Lägg till eller uppdatera validation commands om de saknas.\n\n## P1 — fixa sedan\n- Förbättra exempel, screenshots eller demo-output där det hjälper repoets publika förståelse.\n- Lägg till tydligare issue/PR-mallar om repoet saknar styrning.\n- Dela övervuxna docs i små context surfaces.\n\n## P2 — polish\n- Gör README kortare om den duplicerar djupare docs.\n- Lägg till mer kompakta testprompter för Codex/Claude/ChatGPT.\n- Skapa en liten roadmap med nästa 3 PR-slices.\n\n## Suggested PR slices\n1. docs: tighten read-order and truth-boundary section\n2. tests: add/verify context budget and public-safe validation\n3. examples: add one sanitized end-to-end context-pack example\n\n## Confidence\nMedium. This MVP did not perform a full live GitHub scan unless observations were provided by an adapter.\n"""

def _architecture_decision(task: str) -> str:
    return f"""# Architecture Decision\n\n## Goal\n{task}\n\n## Requirements\n- Säker styrning\n- Tydliga trust boundaries\n- Stegvis införande\n- Mätbar kvalitet och kostnad\n- Möjlighet att byta komponenter senare\n\n## High-level design\nBygg runt ett kontrollplan: identitet, policy, gateway, observability och tydlig datagräns.\nLåt implementationer/modeller vara utbytbara bakom stabila kontrakt.\n\n## Risks\n- För brett scope i första versionen\n- Oklara informationsklasser\n- Leverantörslåsning\n- Otillräcklig logging eller för innehållsrik logging\n- Ingen exit-plan\n\n## Options\n1. Köp färdig tjänst — snabbast, men mest låsning.\n2. Bygg själv — mest kontroll, men dyrast och långsammast.\n3. Hybrid — bäst balans när säkerhet och snabb nytta båda spelar roll.\n\n## Recommendation\nVälj hybrid som default om kraven innehåller både snabb införing och stark kontroll.\n\n## Next step\nDefiniera en 6–12 veckors pilot med tydliga go/no-go-kriterier.\n\n## Confidence\nMedium. Faktiska krav, juridik och produktdetaljer måste verifieras.\n"""

def _root_cause(task: str) -> str:
    return f"""# Root Cause Analysis\n\n## Problem\n{task}\n\n## Symptoms vs causes\n- Symptom: det synliga problemet eller upprepade stoppet.\n- Contributing factors: process, verktyg, otydligt ägarskap eller sena kontroller.\n- Possible root cause: systemet saknar tidig feedback, tydliga gates eller ansvar.\n\n## Causal chain\nTrigger\n↓\nSen upptäckt / otydlig signal\n↓\nManuell tolkning eller brist på ansvar\n↓\nFlödet fastnar i sista steget\n\n## Likely root cause\nKontrollerna kommer för sent eller är för otydliga för att teamet ska kunna agera tidigare.\n\n## Leverage points\n- Flytta kontroller tidigare.\n- Gör stoppsignaler maskinläsbara.\n- Definiera ägare för varje gate.\n- Mät återkommande stopporsaker.\n\n## Recommended actions\n1. Logga de senaste 5 stopporsakerna.\n2. Dela dem i policy, test, review, release eller ägarskap.\n3. Flytta vanligaste stoppet till tidigare fas.\n4. Skapa en enkel check innan sista steget.\n\n## Confidence\nMedium without concrete incident data.\n"""

def _decision_tradeoff(task: str) -> str:
    return f"""# Decision & Trade-off\n\n## Decision\n{task}\n\n## Options\n1. Minimal path — snabbt, låg risk, men begränsad effekt.\n2. Balanced path — lagom scope, tydlig kvalitet, bra för nästa steg.\n3. Ambitious path — hög effekt, men större komplexitet och risk.\n\n## Trade-offs\n- Speed vs control\n- Simplicity vs flexibility\n- Short-term delivery vs long-term maintainability\n- Manual work vs automation\n\n## Recommendation\nVälj balanced path om beslutet påverkar fler än ett arbetsflöde eller repo.\n\n## Next step\nSkriv ned beslutets success criteria innan implementation.\n\n## Confidence\nMedium.\n"""

def _learning(task: str) -> str:
    return f"""# Explanation\n\n## Simple explanation\n{task}\n\nTänk på det som ett system där du först vill förstå vad saken gör, sedan varför den finns, och till sist hur du kan använda den utan att blanda ihop den med andra saker.\n\n## Common confusion\nMånga blandar ihop verktyget, processen, minnet och resultatet. Separera dessa så blir systemet lättare att förstå.\n\n## Example\nOm Atlas är en loop, är prompten inte motorn. Prompten är mer som instruktionen på instrumentpanelen.\n\n## Understanding check\nKan du beskriva skillnaden mellan en router och en executor i en mening?\n\n## Confidence\nMedium.\n"""

def _prompt_improvement(task: str) -> str:
    return f"""# Prompt Improvement\n\n## Goal\n{task}\n\n## Diagnosis\nEn stark prompt ska inte försöka bära hela systemet själv. Den ska definiera roll, gränser, route-regler, output och quality gates.\n\n## Failure modes\n- För lång prompt som blandar policy, minne och output.\n- Router som väljer prompt men inte kör svaret.\n- Otydliga stop-regler.\n- Inga testfall.\n\n## Better structure\n1. Trigger\n2. Task classification\n3. Route selection\n4. Execution rule\n5. Evaluation rule\n6. Output format\n7. Safety/write boundary\n8. Test cases\n\n## Recommendation\nGör prompten till ett tunt gränssnitt ovanpå en loop/state-machine.\n\n## Next step\nSkriv routes som data, inte som långa promptstycken.\n\n## Confidence\nHigh.\n"""

def _general(task: str) -> str:
    return f"""# Answer\n\n## Goal\n{task}\n\n## Response\nAtlas Core hanterar detta som en generell uppgift. För ett starkare svar, ge mer kontext eller välj en specifik route.\n\n## Recommendation\nAnvänd en specifik route om uppgiften är större än en enkel fråga.\n\n## Next step\nKör igen med mer konkret mål, constraints och önskat format.\n\n## Confidence\nLow-to-medium.\n"""
