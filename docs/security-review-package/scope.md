# Scope

Code security baseline: `6474f17d4ca6fa75d56f29d2475ad4bfcb1c7d60`

## In scope

- Python package `atlas_core/` (no runtime dependencies; `pyproject.toml`
  declares `dependencies = []`)
- Public CLI `atlas` (`atlas_core/cli.py`), including `atlas run` and
  `atlas propose`
- Python host API: `AtlasController.run(..., limits=RunLimits(...))`,
  `run_isolated`, `ToolGateway`, `ApprovalAuthority`
- Bundled adapters in `atlas_core/adapters/`: filesystem reader, GitHub reader,
  live model adapter (Ollama / OpenAI-compatible), MQ/mqobsidian adapters
- CI and release tooling: `.github/workflows/test.yml`, `run-atlas.yml`,
  `pages.yml`, `.github/dependabot.yml`, `uv.lock`, `.secrets.baseline`,
  `scripts/reproducible_build.py`, `scripts/secret_scan_smoke.py`
- GitHub repository settings for `main` as far as they are observable
  (see [`hosting-controls.md`](hosting-controls.md))

## Out of scope

- Third-party or host-supplied adapters, tool handlers and model providers.
  The documented contract is that only trusted host code registers them
  (`docs/safety-model.md`).
- The behaviour of an external LLM. Core does not claim a model ignores
  malicious input; it claims that model text cannot grant itself tools or
  write access.
- Atlas One, atlas-loop and the MQ repositories, except for the adapter
  contracts in this repository.
- OS-level sandboxing. Core does not provide one and says so.

## Trust boundaries

| Boundary | Trusted side | Untrusted side |
| --- | --- | --- |
| Repository content | Core, host | Files read from the observed repository (local or GitHub) |
| Model output | Core's gateway and approval checks | Everything the model returns, including claims of approval |
| Tool registration | Host code holding the `ToolGateway` | Model requests for tools |
| Write approval | Host holding `ApprovalAuthority` and an approval channel outside the proposing process | Model, task text, patch content, CLI stdin |
| Environment | Host process | `ATLAS_MODEL_*`, `GITHUB_TOKEN`/`GH_TOKEN` values are read from it |
| CI | Pinned actions, locked dependencies | Pull request content |

## Entry points

| Entry point | Mode | Notes |
| --- | --- | --- |
| `atlas run TASK [--repo-path P] [--repo OWNER/NAME]` | Read-only, bounded worker on POSIX | Windows fails closed for the bounded CLI |
| `atlas run --unsafe-legacy-unbounded ...` | Unbounded, legacy | Explicitly not sandboxed or bounded |
| `atlas propose` | One approved write: create `refs/heads/atlas/<name>` | Runs the caller-supplied test command as the caller |
| `atlas create/status/cancel/events/inspect/metrics` | Event log and sidecar lock/cancel files | Paths are caller-supplied |
| `atlas feedback record/promote` | Appends to `candidates.jsonl` / `learnings.jsonl` under `--store` | Path is caller-supplied |
| `atlas generate-skill OUTPUT_DIR [--force]` | Writes generated skill files | `--force` overwrites |
| `AtlasController.run(..., limits=...)` | In-process, cooperative budget | Not a hard timeout |
| `run_isolated(...)` | Spawned POSIX worker, hard deadline | Trusted, picklable callbacks only |
| `atlas_core.worker_cli` | Private | Direct invocation bypasses the parent; not supported |
| `run-atlas.yml` (`workflow_dispatch`) | CI, `contents: read`, `actions: read` | Inputs passed via `env`, not `${{ }}` interpolation |
