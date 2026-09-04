---
name: atlas-dependency-analysis
description: Build and analyze verified Atlas Core dependency graphs for routes, loop stages, adapters, schemas, tools, and approval boundaries. Use for architecture impact, adapter design, cycle detection, ownership, coupling, or blast-radius analysis.
---

# Atlas Dependency Analysis

Derive every edge from current code, contracts or runtime evidence. Similar names are not evidence of a dependency.

## Workflow

1. Define node and edge types before collecting data.
2. Read the smallest relevant surface: imports and calls, adapter protocols, route data, schemas, CLI wiring and tests.
3. Record evidence for every edge using a portable repository-relative reference.
4. Analyze only what answers the question: cycles, connected components, fan-in/fan-out, articulation points or shortest dependency paths.
5. Validate surprising edges against source before reporting them.
6. Produce Mermaid for human review and JSON only when machine reuse is requested.

## Minimal graph contract

```json
{
  "nodes": [{"id": "controller", "kind": "component"}],
  "edges": [
    {
      "source": "controller",
      "target": "evaluator",
      "kind": "calls",
      "evidence": "atlas_core/controller.py"
    }
  ]
}
```

## Guardrails

- Keep Atlas Core independent from MQ; MQ is an optional adapter boundary.
- Do not treat centrality as product importance or an import as proof of runtime execution.
- Do not add NetworkX or another runtime dependency unless the task demonstrably requires it and the user approves.
- Do not change code while performing a requested read-only architecture analysis.

## Atlas sources

Start with `atlas_core/controller.py`, `atlas_core/adapters/base.py`, `atlas_core/router.py`, `routes/routes.json`, schemas and relevant tests.
