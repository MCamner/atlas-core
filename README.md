# Atlas Core

<p align="center">
  <strong>Standalone loop engine for routed, evaluated, retryable AI-assisted work.</strong>
</p>

<p align="center">
  <a href="https://github.com/MCamner/atlas-core/actions/workflows/test.yml"><img alt="Tests" src="https://github.com/MCamner/atlas-core/actions/workflows/test.yml/badge.svg"></a>
  <a href="https://github.com/MCamner/atlas-core/actions/workflows/run-atlas.yml"><img alt="Run Atlas Core" src="https://github.com/MCamner/atlas-core/actions/workflows/run-atlas.yml/badge.svg"></a>
  <img alt="Python" src="https://img.shields.io/badge/python-3.11%2B-blue">
  <img alt="Status" src="https://img.shields.io/badge/status-experimental-orange">
  <img alt="License" src="https://img.shields.io/badge/license-MIT-green">
</p>

---

## About

**Atlas Core** is the independent engine behind the Atlas 2.0 idea: a bounded task loop that can observe context, choose a route, plan the next action, execute, evaluate the result, retry when useful, and stop when the answer is good enough.

It is intentionally separate from the MQ stack.

MQ, GitHub, Obsidian, ChatGPT Skills, and local memory should plug in as adapters — not become the core.

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

## What it can do now

This v0.2.0 is a working scaffold:

- deterministic route selection
- route map
- task planner
- rule-based executor
- evaluator
- bounded max-iteration loop
- local memory candidate adapter
- local filesystem repo observations
- public GitHub repo observations
- JSON schemas
- tests
- GitHub Actions runner
- optional ChatGPT Skill wrapper

It does **not** include a live LLM provider by default. Add that as an adapter later.

## Install locally

```bash
git clone https://github.com/MCamner/atlas-core.git
cd atlas-core
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
python -m unittest discover -s tests
```

For pytest-based local checks:

```bash
python -m pip install pytest
python -m pytest -q
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

## Run with repo observations

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

## Core commands

```bash
atlas run "<task>"
atlas routes
atlas version
```

## GitHub Actions

This repo includes a manual loop runner:

```text
.github/workflows/run-atlas.yml
```

Run it from GitHub:

```text
Actions → Run Atlas Core → Run workflow
```

Or trigger it with GitHub CLI:

```bash
gh workflow run "Run Atlas Core" \
  --field task="granska atlas-core och hitta nästa bästa förbättring" \
  --field json_output="false"
```

Download the result artifact:

```bash
RUN_ID=$(gh run list \
  --workflow="run-atlas.yml" \
  --json databaseId,conclusion \
  --jq '[.[] | select(.conclusion=="success")][0].databaseId')

gh run download "$RUN_ID" -n atlas-result -D atlas-runs
cat atlas-runs/atlas-result.md
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

## Recommended roadmap

```text
v0.1  Core loop scaffold
v0.2  Repo observations + GitHub Actions runner
v0.3  LLM adapter contract
v0.4  mqobsidian adapter
v0.5  ChatGPT Skill package generator
v1.0  Stable Atlas Loop API
```

## Project position

Atlas Core is not another prompt pack.

It is the small independent runtime layer that turns Atlas from:

```text
prompt → answer
```

into:

```text
state → route → plan → execute → evaluate → final
```

That separation matters. Prompts can change. Adapters can change. The loop contract should stay stable.
