# Roadmap

Atlas Core should grow carefully. The goal is a small stable loop contract, not a large framework too early.

## Version plan

```text
v0.1  Core loop scaffold
v0.2  Repo observations + GitHub Actions runner
v0.3  LLM adapter contract
v0.4  mqobsidian adapter
v0.5  ChatGPT Skill package generator
v1.0  Stable Atlas Loop API
```

## v0.2 — shipped scaffold

Capabilities:

- deterministic routing
- route map
- planning
- rule-based execution
- evaluation
- bounded iterations
- local memory candidates
- local repo observations
- public GitHub repo observations
- GitHub Actions runner

## v0.3 — shipped scaffold

Goal:

```text
Make live model execution pluggable without coupling the core to one provider.
```

Expected work:

- model adapter interface
- rule-based fallback
- provider-neutral result schema
- test fixtures for model outputs
- safety checks before write-like tool use

Status:

- implemented as optional `ModelAdapter`
- rule-based executor remains default when no adapter is configured
- controller records provider-neutral model metadata in run metadata
- a raising or malformed adapter ends the run as `failed`, and does not fall
  back to the rule-based executor — that would report a template as a model
  answer
- `StubModelAdapter` ships for tests and CI without a provider
- timeouts stay the adapter's responsibility; `execute()` is synchronous and
  the core cannot cancel one in progress
- tests cover adapter output, fallback, failure handling, and write approval
  gating

## v0.4 — shipped scaffold

Goal:

```text
Read durable memory/context from mqobsidian without making MQ mandatory.
```

Expected work:

- read context packs
- read project memory
- write memory candidates only
- preserve source-of-truth boundaries
- no direct runtime truth from memory alone

Status:

- optional `MQObsidianMemoryAdapter` with no MQ package dependency
- bounded reads follow mqobsidian's compact context-surface order
- observations are labelled as durable memory, not runtime truth
- writes accept memory candidates only
- controller and CLI integration covered by tests

## v0.5 — shipped scaffold

Goal:

```text
Generate a thin ChatGPT Skill wrapper around Atlas Core behavior.
```

Expected work:

- skill template
- route summary
- command examples
- safety boundaries
- regression tests for route-and-execute behavior

Status:

- `atlas generate-skill <output-dir>` creates an installable skill package
- generated `SKILL.md` delegates execution to the Atlas CLI
- route reference is generated from the live route map
- command examples and mutation approval boundaries are included
- tests cover generation, overwrite protection, CLI use, and checked-in drift

## v1.0 — shipped scaffold

Goal:

```text
Make the loop contract stable enough for real adapters.
```

Expected guarantees:

- stable state schema
- stable route schema
- stable evaluation schema
- clear adapter contract
- consistent stop rules
- documented write boundary

Status:

- public controller, state, route, plan, evaluation, and model types exported
- versioned closed schemas for runs, routes, evaluations, and memory candidates
- terminal runs expose explicit, tested stop reasons
- positive iteration bounds are enforced
- adapter and write boundaries are documented as the 1.x compatibility contract

## Non-goals

Atlas Core should not become:

- a prompt library only
- an MQ-specific tool
- a hidden automation runner
- an unbounded autonomous agent
- a replacement for source repo truth

## Product direction

Atlas Core should be boring in the best way:

```text
small loop
clear state
bounded execution
explicit evaluation
safe adapters
```
