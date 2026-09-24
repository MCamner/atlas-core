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

<p align="center">
  <a href="https://mcamner.github.io/atlas-core/">Site</a> ·
  <a href="https://github.com/MCamner/atlas-core/wiki">Wiki</a> ·
  <a href="CHANGELOG.md">Changelog</a>
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

This v1.0.0 release provides a stable loop scaffold:

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
- optional model and mqobsidian adapters
- ChatGPT Skill package generator
- versioned run, route, evaluation, and memory-candidate schemas
- explicit terminal stop reasons

It does **not** include a live LLM provider by default. Add one through the
stable model adapter contract.

## Quick start

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

Persist the append-only event log and inspect one run later:

```bash
atlas run "granska atlas-core" --repo-path . --event-log .atlas/events.jsonl --json
atlas inspect <run-id> --event-log .atlas/events.jsonl
atlas inspect <run-id> --event-log .atlas/events.jsonl --json
```

The text report names the observed sources, unresolved evidence gaps and stop
reason. The JSON form is the machine-readable `atlas-inspect.v1` export and
includes the validated events for that run. Inspection is read-only and fails
on malformed or contradictory history instead of repairing it. A JSONL file may
contain several runs when writes are serialized; concurrent runs should use
separate event-log paths because shared-file writer locking is not provided.

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

## Run with mqobsidian memory

Read compact project context and write the resulting memory candidate to the
vault inbox:

```bash
atlas run "granska nästa arkitekturbeslut" \
  --mqobsidian-path /path/to/mqobsidian \
  --mq-project atlas-core
```

mqobsidian observations are durable memory, not current runtime truth. Combine
them with `--repo-path` or `--repo` when the task depends on current code or CI.

## Core commands

```bash
atlas run "<task>"
atlas inspect <run-id> --event-log <events.jsonl> [--json]
atlas routes
atlas generate-skill ./generated-skills
atlas version
```

`generate-skill` creates `atlas-core-loop/SKILL.md` plus a route reference from
the current route map. It refuses to overwrite an existing package unless
`--force` is passed.

`atlas run` exits with the terminal state, so a script does not have to read
the output to know what happened:

| Code | Meaning |
| --- | --- |
| 0 | Passed its quality gate. |
| 1 | The run failed. |
| 2 | Finished without passing — for example a repo review with no sources. |
| 3 | A mutation needs approval first. |

Exit 2 is not an error. It is the loop stopping honestly instead of claiming an
answer it cannot support.

## Editor and MCP configuration

Atlas Core needs no MCP server, editor plugin or agent configuration. It
declares no dependencies, and `pip install -e .` plus the test suite is the
whole setup.

Any such configuration is therefore local and untracked. `.mcp.json`,
`.cursor/` and `.vscode/` are in `.gitignore`: keep your own copies if you use
them — for example an `.mcp.json` pointing at the NotebookLM VS Code extension —
and they will stay out of commits. They name absolute paths on one machine, so
they describe a workstation rather than this repository.

## Example output

A real run against this repository, abbreviated — the body sections and the
observed file contents under `Sources inspected` are truncated here. The trailer
after `---` is the loop's own accounting: which route it picked, how many
iterations it used against the bound, and whether evaluation let it stop.

Note the route: the task says `atlas`, so the router picks `prompt_improvement`,
not `repo_review`. The `--repo-path` observations still reach the output —
every route renders what it was given under `Sources inspected`.

```text
$ atlas run "granska atlas-core och hitta nästa bästa förbättring" --repo-path .

# Prompt Improvement

## Goal
granska atlas-core och hitta nästa bästa förbättring

## Failure modes
- För lång prompt som blandar policy, minne och output.
- Router som väljer prompt men inte kör svaret.
- Otydliga stop-regler.
- Inga testfall.

## Recommendation
Gör prompten till ett tunt gränssnitt ovanpå en loop/state-machine.

## Next step
Skriv routes som data, inte som långa promptstycken.

## Confidence
High.

## Sources inspected
- Local repo path: /path/to/atlas-core
- README.md:
# Atlas Core
...
- pyproject.toml:
[build-system]
...

---
Atlas route: prompt_improvement
Iterations: 1/2
Stop reason: passed (evaluation)
Criteria met: 1.0
Status: passed
```

`atlas routes` prints the full route map as JSON, including the keywords each
route matches and its risk level.

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

## Security and safe sharing

Atlas Core is read-only by default. It ships no LLM provider and no write
adapter: the only files it writes are local memory candidates under a directory
you pass with `--memory-dir`.

Before sharing a run log or an artifact from the Actions runner, check it the
way you would check any output that quotes your filesystem:

- run output embeds observed repo content, including README text and file paths
- `--repo-path` observations come from your local checkout
- `--repo` observations come from the public GitHub REST API and carry no token
- local memory candidates are written as plain JSON, not encrypted

The workflow runner passes its inputs through environment variables rather than
shell interpolation, and requests only `contents: read` and `actions: read`.

The full model, including where the read-only boundary is enforced and where it
is only advisory, is in [docs/safety-model.md](docs/safety-model.md).

## Design principles

1. Atlas Core must run without MQ.
2. MQ must be an adapter.
3. Read-only by default.
4. No write actions without explicit approval.
5. Max iterations must be bounded.
6. Evaluation must decide whether to finish, retry, ask for approval, or request more context.
7. Memory is optional and adapter-driven.
8. No hidden repo or runtime assumptions.

## Roadmap

Atlas Core v1.0.0 stabilises the loop API. Continued work on evidence
verification, robust execution and integrations is tracked in
[ROADMAP.md](ROADMAP.md).

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
