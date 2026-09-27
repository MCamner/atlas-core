# Test Evidence

Review target: `07ac3944db800b28bfc41fcd933cd10d6b04c00d`

## CI on the review target

- Workflow: `test` (`.github/workflows/test.yml`), job `python`
- Run: [36292102442](https://github.com/MCamner/atlas-core/actions/runs/36292102442)
- Event: `push` to `main`; head SHA equals the review target
- Conclusion: `success`; every step succeeded
- Unit tests: `Ran 1009 tests`, `OK (skipped=3)`
- `pip-audit --strict`: `No known vulnerabilities found`

The job runs, in order: `uv lock --check`, `uv sync --locked --group ci`,
unittest discovery, mypy, pyright, `pip-audit --strict`, the secret-scan
canary, `detect-secrets-hook` over tracked files, the reproducible build
check, and the runtime SBOM export. See `.github/workflows/test.yml` for the
exact commands.

## Reproducing locally

```sh
git checkout 07ac3944db800b28bfc41fcd933cd10d6b04c00d
uv lock --check
uv sync --locked --group ci
uv run --locked --group ci python -m unittest discover -s tests
uv run --locked --group ci pip-audit --strict
uv run --locked --group ci python scripts/secret_scan_smoke.py
git ls-files -z -- . ':!.secrets.baseline' \
  | xargs -0 uv run --locked --group ci detect-secrets-hook --baseline .secrets.baseline
```

Use `unittest discover`, as CI does. Running `pytest` from the repository root
stops at collection with `ModuleNotFoundError: No module named 'scripts'` in
`tests/test_reproducible_build.py`. The same command is used in
`.github/workflows/run-atlas.yml`; that workflow has not run since the test was
added. This is an operational defect in the workflow, not a gap in the `test`
gate.

The number of skipped tests depends on the platform and on optional local
repositories (MQ contract tests skip without configured paths).

## Security-relevant test files

| Area | Test files |
| --- | --- |
| Prompt injection, tool gateway | `test_p03_attack_matrix.py`, `test_tool_gateway.py`, `test_model_capabilities.py` |
| Write approval | `test_approval.py`, `test_patch_proposal.py` |
| Path containment, integrity | `test_integrity.py`, `test_snapshot.py`, `test_observation.py`, `test_finding.py`, `test_adapters.py` |
| Redaction, secrets | `test_redaction.py`, `test_live_provider.py` |
| Bounds, isolation | `test_p03_bounded_cli.py`, `test_p03_hard_cli.py`, `test_p03_isolation.py`, `test_p03_controller.py`, `test_budget_concurrency.py`, `test_prompt_bounds.py`, `test_partial_reads.py`, `test_platform_locks.py` |
| Release integrity | `test_reproducible_build.py`, `test_release_metadata.py` |

These tests were written by the implementers. They show the behaviour the
authors intended to hold; they do not show that no other path exists.
