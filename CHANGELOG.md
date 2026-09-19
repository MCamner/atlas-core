# Changelog

## Unreleased

## v1.0.0 — 2026-09-19

First stable release. Makes the engine do what the README describes.

- Retry is now a replan: the previous evaluation is passed into the executor,
  which closes the specific sections the evaluator named as missing. The
  unconditional "Loop improvement" note that claimed an improvement no
  iteration had made is gone.
- Evaluation retries only when a gap is actionable. A deterministic rerun with
  identical input no longer burns an iteration.
- `repo_review` and `learning` now emit the `Recommendation` and `Next step`
  sections the evaluator grades them on; `root_cause` gained `Next step`. Every
  shipped route can now pass its own quality gate on the first iteration.
- Observations reach every route, not just `repo_review`, and are rendered under
  `## Sources inspected`.
- `AtlasEvaluation` gained `missing_sections`: machine-readable gap codes shared
  by the evaluator and the executor.
- `--json` output carries `"schema": "atlas-run.v1"`, and `schemas/` now
  describes the documents the engine actually emits. `tests/test_schemas.py`
  checks them against each other.
- The write-action notice moved from the observation list to
  `metadata.safety_notice`; a warning is not a source.
- `AtlasController.run` no longer appends to the caller's `observations` list.
- `docs/safety-model.md` now states where the read-only boundary is enforced and
  where it is only advisory, as the README claims it does.
- Added the v0.3 model adapter scaffold: optional `ModelAdapter`,
  provider-neutral `ModelResult`, rule-based fallback, and tests for model
  output plus write-approval gating.
- Added the v0.4 mqobsidian adapter scaffold: bounded compact-context reads,
  explicit durable-memory labelling, candidate-only writes, and optional
  controller/CLI integration without an MQ package dependency.
- Added the v0.5 ChatGPT Skill package generator with live route summaries,
  CLI examples, safety boundaries, overwrite protection, and drift tests for
  the checked-in integration package.
- Stabilized the v1.0 loop API with public type exports, explicit stop reasons,
  positive iteration bounds, closed versioned schemas, and a documented 1.x
  adapter and write-boundary contract.

## v0.2.0 — 2026-07-31

Adds repo observation support and GitHub Actions runner.

- CLI flags: `--repo`, `--repo-ref`, `--repo-path`
- `GitHubRepoAdapter` using GitHub REST API
- `FilesystemRepoAdapter` for local repo context
- `run-atlas.yml` workflow_dispatch runner
- GitHub reader adapter docs

## v0.1.0 — 2026-07-31

Initial standalone Atlas Core MVP.
