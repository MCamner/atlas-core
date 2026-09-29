# Working in Atlas Core

Instructions for coding agents (Codex, Claude Code and others) that change
this repository. `CLAUDE.md` points here, so there is one source.

To *use* Atlas rather than change it, see the skill in
[`integrations/chatgpt-skill/SKILL.md`](integrations/chatgpt-skill/SKILL.md).

## Where things are

- `atlas_core/`: the package. The loop is in `controller.py`, routing in
  `router.py` and `review_plan.py`, deterministic review producers in
  `review_producers.py`, adapters in `adapters/`.
- `docs/api-contract.md`: the public CLI, stop reasons and exit codes.
  `docs/safety-model.md`: the enforced boundaries.
- `ROADMAP.md`: what is done and what gates the next release.

## Checks

Run what CI runs (`.github/workflows/test.yml`), in this order:

```sh
uv lock --check
uv sync --locked --group ci
uv run --locked --group ci python -m unittest discover -s tests
uv run --locked --group ci mypy atlas_core tests scripts/pinned_repo_review.py scripts/secret_scan_smoke.py
uv run --locked --group ci pyright atlas_core tests scripts/pinned_repo_review.py scripts/secret_scan_smoke.py scripts/reproducible_build.py
uv run --locked --group ci pip-audit --strict
git ls-files -z -- . ':!.secrets.baseline' | xargs -0 uv run --locked --group ci detect-secrets-hook --baseline .secrets.baseline
```

- Use `unittest` like CI. Plain `pytest` stops at collection on the
  `scripts` import, and `python -m pytest` runs but skips more tests.
- Run both mypy and pyright. Each finds errors the other does not.
- The secrets hook refuses an unstaged `.secrets.baseline`. Stage it first
  if you changed it.
- CI also runs an end-to-end review against a pinned mq-agent commit and a
  reproducible build. Those need no local step unless you change them.

## Rules for changes

- Write the failing test first for a fix or a feature, then the change.
- Keep a change to its task. No drive-by refactoring.
- Record user-visible changes in `CHANGELOG.md` under `Unreleased`.
- `.secrets.baseline`: when a change moves a known false positive, edit only
  its `line_number` by hand. Do not keep the filter entries or timestamp the
  hook writes when it regenerates the file.
- `integrations/chatgpt-skill/` is generated. Change
  `atlas_core/skill_generator.py`, then regenerate:
  `atlas generate-skill --force <dir>` and copy the files over.
  `tests/test_skill_generator.py` fails when they differ.
- A deterministic producer must decline (return nothing) when it cannot read
  everything its verdict depends on. A wrong `passed` is worse than a stop.
- The v2.0 security review covers `v1.0.0` only. Name a PR in the
  next-release security gate in `ROADMAP.md` when it changes what Atlas
  reads, runs, writes or sends, or what CI trusts:
  - code under `atlas_core/` that routes, observes, runs, evaluates,
    approves or writes (for example the controller, adapters, snapshot,
    producers, claim checks, approval, CLI);
  - `.github/workflows/`, `pyproject.toml`, `uv.lock` or `scripts/` used by
    CI or the release build.

  Do not name a PR that changes only documentation, tests or generated text
  (such as the skill template in `skill_generator.py`).

## Pull requests and merges

- `main` is protected: a PR, the `python` check and an up-to-date branch are
  required.
- The maintainer reviews every PR. Do not merge unless asked to.
- Squash merge on the reviewed head: `gh pr merge <n> --squash
  --match-head-commit <sha>`.
- A PR counts as verified only when the `test` workflow's `push` run has
  passed on the exact merge commit on `main`.
- Other work lands on `main` in parallel. Fetch before building on it.
