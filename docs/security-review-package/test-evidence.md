# Test Evidence

Code security baseline: `6474f17d4ca6fa75d56f29d2475ad4bfcb1c7d60`

## CI on the code baseline

- Workflow: `test` (`.github/workflows/test.yml`), job `python`
- Run: [36297845486](https://github.com/MCamner/atlas-core/actions/runs/36297845486)
- Event: `push` to `main`; head SHA equals the code baseline
- Conclusion: `success`; every step succeeded
- Unit tests: `Ran 1021 tests`, `OK (skipped=3)`
- `pip-audit --strict`: `No known vulnerabilities found`

The job runs, in order: `uv lock --check`, `uv sync --locked --group ci`,
unittest discovery, mypy, pyright, `pip-audit --strict`, the secret-scan
canary, `detect-secrets-hook` over tracked files, the reproducible build
check, and the runtime SBOM export. See `.github/workflows/test.yml` for the
exact commands.

Each fix in [`pre-review-findings.md`](pre-review-findings.md) also has its
own green `push` run on its merge SHA, listed there.

## Reproducing locally

```sh
git checkout 6474f17d4ca6fa75d56f29d2475ad4bfcb1c7d60
uv lock --check
uv sync --locked --group ci
uv run --locked --group ci python -m unittest discover -s tests
uv run --locked --group ci pip-audit --strict
uv run --locked --group ci python scripts/secret_scan_smoke.py
git ls-files -z -- . ':!.secrets.baseline' \
  | xargs -0 uv run --locked --group ci detect-secrets-hook --baseline .secrets.baseline
```

Use `unittest discover`, as both workflows do. Running `pytest` from the
repository root stops at collection with `ModuleNotFoundError: No module
named 'scripts'` in `tests/test_reproducible_build.py`.

The number of skipped tests depends on the platform and on optional local
repositories (MQ contract tests skip without configured paths).

## Security-relevant test files

| Area | Test files |
| --- | --- |
| Prompt injection, tool gateway | `test_p03_attack_matrix.py`, `test_tool_gateway.py`, `test_model_capabilities.py` |
| Write approval | `test_approval.py`, `test_patch_proposal.py` |
| Path containment, integrity | `test_integrity.py`, `test_snapshot.py`, `test_observation.py`, `test_finding.py`, `test_adapters.py` |
| Redaction, secrets | `test_redaction.py`, `test_live_provider.py` |
| Network credentials, response bounds | `test_redirect_credentials.py`, `test_provider_response_bound.py` |
| Bounds, isolation | `test_p03_bounded_cli.py`, `test_p03_hard_cli.py`, `test_p03_isolation.py`, `test_p03_controller.py`, `test_budget_concurrency.py`, `test_prompt_bounds.py`, `test_partial_reads.py`, `test_platform_locks.py` |
| Release integrity | `test_reproducible_build.py`, `test_release_metadata.py` |

These tests were written by the implementers. They show the behaviour the
authors intended to hold; they do not show that no other path exists.
