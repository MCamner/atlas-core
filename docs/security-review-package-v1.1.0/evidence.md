# Evidence

Pinned release SHA: `83d7d2c12ddaf00454be2adfcb9ceb3a6223552d`

Everything below was **observed by the authors on 2026-10-25**, with the
command that produced it. Re-run what your conclusion depends on; the commands
are in [`review-commands.md`](review-commands.md).

## Exact-main CI

The `test` workflow push run on every merge SHA in the range concluded
`success`. Run IDs are in [`changes.md`](changes.md). On the pinned SHA:

| | |
| --- | --- |
| Run | [40217200863](https://github.com/MCamner/atlas-core/actions/runs/40217200863) |
| Jobs | `python` success, `python310` success |
| Steps of note | Audit locked dependencies; Run Atlas gate-parity loop against real mq-agent; Run negative gate-parity E2E against real mq-agent; Verify reproducible wheel, sdist and release SBOM; both `upload-artifact` steps: all `success` |
| Artifacts | `atlas-core-release-integrity` (595112 bytes, `sha256:5a3cb13ba15df314d805c144042d0e0df96685f3c76e5bd6199e3ed6c64a0546`), `atlas-core-runtime-sbom` (508 bytes, `sha256:5dc985bc18bde1a50cd12135901e1ceaacf2ea2f05ac80df773f0d83f85e2e3b`). Not expired at observation |

## Local checks at the pinned SHA

Run in a clean detached worktree at `83d7d2c` (`git status --porcelain` empty),
macOS, Python 3.11, uv 0.13.5:

| Check | Result |
| --- | --- |
| `uv lock --check` | Resolved 49 packages |
| `python -m unittest discover -s tests` | Ran 1071 tests, OK (skipped=3) |
| `mypy atlas_core tests scripts/pinned_repo_review.py scripts/secret_scan_smoke.py` | no issues in 127 source files |
| `pyright … scripts/reproducible_build.py` | 0 errors, 0 warnings |
| `pip-audit --strict --disable-pip --require-hashes -r <uv export --all-groups --no-emit-project>` | No known vulnerabilities found (45 packages) |
| `scripts/secret_scan_smoke.py` | detect-secrets detected and rejected the synthetic AWS canary |
| `detect-secrets-hook --baseline .secrets.baseline` over tracked files | passed |

The negative audit check, done for #146: `filelock==4.0.3` reports
CVE-2026-112940, CVE-2026-112913 and CVE-2026-112907, and the audit exits 1.

## Release bundle

Downloaded from run 40217200863 into an empty directory:

| File | SHA-256 (computed) | Manifest |
| --- | --- | --- |
| `atlas_core-1.1.0-py3-none-any.whl` | `271e4ddeca87dbc0eddbee3cb382ce5cfe0c90c40d3e5f5136b1482ebc127709` | matches |
| `atlas_core-1.1.0.tar.gz` | `a0d3870cfa5d271ae9035d7d41813a02fed86eb6ee2a06afecb305e93b154660` | matches |
| `atlas-core-1.1.0.cdx.json` | `79050158f8b47dbb9421016138f4740357846478703d86def7198cc57b387cd8` | matches |
| `release-integrity.json` | `2e9448303fde4abf52255be9cdc2dd15c0057d4b3403319b3b43456ee7a2ea80` | (the manifest) |

The manifest records `source_commit` as `83d7d2c12ddaf00454be2adfcb9ceb3a6223552d`,
`version` as `1.1.0` and `source_date_epoch` as `1792949724`.

**Local rebuild.** `scripts/reproducible_build.py` at the pinned SHA on macOS
produced the same wheel and sdist digests as CI. The SBOM differs only in
`metadata.timestamp`, `serialNumber` and the recorded uv version (0.13.5 locally,
0.12.13 pinned in CI). Its components are identical. The SBOM is therefore not
byte-reproducible across environments; its digest binds the CI copy.

## Unchanged runtime files

`git diff --quiet v1.0.0 83d7d2c -- <file>` holds for:
- `cli.py`, `approval.py`, `tool_gateway.py`, `patch_proposal.py`, `machine.py`, `budget.py`, `worker_cli.py`
- `containment.py`, `integrity.py`, `redaction.py`
- `adapters/github_reader.py`, `adapters/_http.py`

The changed files under `atlas_core/` are:
- `__init__.py` (version), `router.py`, `executor.py`, `controller.py`, `evaluator.py`
- `observer.py`, `snapshot.py`, `evidence.py`, `claim_check.py`
- `review_plan.py`, `review_producers.py`, `skill_generator.py`
- `adapters/filesystem_repo.py`, `adapters/live_model.py` (docstring), `adapters/output_contract.py` (changed by #128, restored by #148; net diff empty)

## Secrets baseline

`git diff v1.0.0 83d7d2c -- .secrets.baseline` moves two `line_number` values:
- `atlas_core/adapters/live_model.py`, from 97 to 94 (#141)
- `tests/test_plan_reaches_its_subject.py`, from 134 to 151 (#129)

The hashes are unchanged and no entry is added.

## Hosting controls

Read through the GitHub REST API on 2026-10-25:

| Setting | Observed |
| --- | --- |
| Branch protection on `main` | PR required. 0 required approvals. Dismiss stale approvals on. Required checks `python` and `python310` (`python310` added on 2026-10-25). Strict on. Enforced for admins. Force pushes and deletion disabled |
| Rulesets | none |
| Collaborators | `MCamner` (admin) only |
| Secret scanning / push protection | enabled / enabled |
| Non-provider patterns, validity checks | disabled |
| Dependabot security updates | disabled |
| Vulnerability alerts (`GET /vulnerability-alerts`) | 404, not enabled |

**PR reviews.** GitHub records no reviews on any PR in the security gate. Each
was merged through `MCamner`. Reviews took place outside GitHub (see
[`README.md`](README.md#reviewer-independence)).
