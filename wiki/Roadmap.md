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

## v0.2 — current scaffold

Current capabilities:

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

## v0.3 — LLM adapter contract

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

## v0.4 — mqobsidian adapter

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

## v0.5 — ChatGPT Skill package generator

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

## v1.0 — stable loop API

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
