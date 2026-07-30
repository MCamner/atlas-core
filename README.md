# Atlas Core

**Atlas Core** is a standalone loop engine for task routing, planning, execution, evaluation, retry, and finalization.

It is intentionally independent from the MQ stack.

MQ, GitHub, Obsidian, ChatGPT Skills, and local memory are adapters — not the core.

```text
Atlas Core
├── observe
├── route
├── plan
├── execute
├── evaluate
├── retry / replan
├── finalize
└── optional memory candidate
```

## Why this exists

Atlas 1.x was a prompt/router system.

Atlas 2.0 should be a loop:

```text
understand → route → plan → execute → evaluate → improve → final
```

The key design shift:

```text
Prompts are policy and method guidance.
The engine is state + routes + tools + evaluation + stop rules.
```

## Install locally

```bash
cd atlas-core-v0.2.0-2026-07-31
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
python -m unittest discover -s tests
```

## Run

```bash
atlas run "granska ett repo och hitta P0/P1/P2 förbättringar"
```

With JSON run log:

```bash
atlas run "bygg målarkitektur för säker AI-assistent" --json
```

With local memory:

```bash
atlas run "förbättra min prompt för repo review" --memory-dir .atlas-memory
```

## Core commands

```bash
atlas run "<task>"
atlas routes
atlas version
```

## Design principles

1. Atlas Core must run without MQ.
2. MQ must be an adapter.
3. Read-only by default.
4. No write actions without explicit approval.
5. Max iterations must be bounded.
6. Evaluation must decide whether to finish, retry, ask for approval, or request more context.
7. Memory is optional and adapter-driven.
8. No hidden repo or runtime assumptions.

## MVP scope

This v0.2.0 is a working scaffold:

- deterministic router
- route map
- planner
- rule-based executor
- evaluator
- max-iteration loop
- local memory adapter
- JSON schemas
- tests
- optional ChatGPT Skill wrapper

It does **not** include a live LLM provider by default. Add that as an adapter later.

## Recommended roadmap

```text
v0.1  Core loop scaffold
v0.2  LLM adapter contract
v0.3  GitHub reader adapter
v0.4  mqobsidian adapter
v0.5  ChatGPT Skill package generator
v1.0  Stable Atlas Loop API
```

## v0.2: Run with repo observations

Read current local repo before routing:

```bash
atlas run "granska atlas-core och hitta nästa bästa förbättring" --repo-path .
```

Read a public GitHub repo through the GitHub REST API:

```bash
atlas run "granska MCamner/mqobsidian och hitta P0/P1/P2 förbättringar" --repo MCamner/mqobsidian
```

Use both local repo and remote repo context:

```bash
atlas run "jämför atlas-core mot mqobsidian-adapterbehov" --repo-path . --repo MCamner/mqobsidian
```

## GitHub Actions

This repo includes:

```text
.github/workflows/run-atlas.yml
```

Run it from GitHub:

```text
Actions -> Run Atlas Core -> Run workflow
```
