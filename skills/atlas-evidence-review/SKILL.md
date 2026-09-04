---
name: atlas-evidence-review
description: Review Atlas Core run verdicts, quality scores, diagnoses, and recommendations against current observations and evaluation evidence. Use for run-log review, evaluator changes, root-cause claims, retry decisions, or confidence audits.
---

# Atlas Evidence Review

Keep confidence proportional to evidence. Treat a plausible explanation as unconfirmed until current observations support it.

## Workflow

1. State the claim and what would confirm or falsify it.
2. Trace the claim through `AtlasRunState`: task, observations, route, plan, output, evaluation, iteration and final status.
3. Separate observed facts, interpretation and recommendation.
4. Check counterevidence, missing observations, stale inputs, partial repository scans and route-selection bias.
5. Label the verdict `confirmed`, `supported`, `uncertain`, `contradicted` or `not-testable`.
6. Name the smallest read-only check that would reduce uncertainty.

## Output

| Claim | Evidence | Counterevidence | Verdict | Next check |
| --- | --- | --- | --- | --- |
| <precise claim> | <state field, source or test> | <conflict or none found> | <label and reason> | <bounded check> |

## Guardrails

- Do not turn a quality score into evidence by itself.
- Do not infer causality from route selection or a single run.
- Do not use stale examples or documentation as runtime truth.
- Do not assign numeric confidence without a defined calibration method.
- Preserve Atlas Core's read-only default and approval boundary.

## Atlas sources

Inspect only what the task needs:

- `atlas_core/state.py`
- `atlas_core/evaluator.py`
- `atlas_core/controller.py`
- `schemas/atlas-evaluation.v1.json`
- relevant tests or JSON run output
