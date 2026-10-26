# Evidence

Pinned release SHA: `7d0d86c3ee88a8b2c62938d36d9fc77ae6fcfd58`

The authors observed everything below on 2026-10-25 and 2026-10-26, with the
command that produced it. Re-run what your conclusion depends on; the commands
are in [`review-commands.md`](review-commands.md).

## Exact-main CI

The `test` workflow push run on every merge SHA in the range concluded
`success`. The run IDs are in [`changes.md`](changes.md). On the pinned SHA:

| | |
| --- | --- |
| Run | [40243597308](https://github.com/MCamner/atlas-core/actions/runs/40243597308) |
| Jobs | `python`: success. `python310`: success. Both ran the unit tests, OK (skipped=3) |
| Steps of note | All `success`: Audit locked dependencies; Run Atlas gate-parity loop against real mq-agent (`E2E_PASS`); Run negative gate-parity E2E against real mq-agent (`NEGATIVE_E2E_PASS`); Verify reproducible wheel, sdist and release SBOM; both `upload-artifact` steps |
| Artifacts | `atlas-core-release-integrity` (`sha256:2b41f31fb86a31bc0721b5540011bb1948505d668bc8f4caf12c06337d8469c2`), `atlas-core-runtime-sbom` (`sha256:063e47311feaceb5130752665174745ce4a79ed0c204f07011f4de2abfceacc3`) |

The SEC-01 fix, #151, also had exact-head CI on `3fe0687` before it was merged:
run 40242130560, both jobs and both E2Es green. Its exact-main run on `85e2a23`
is 40242236487.

## Local checks at the pinned SHA

These ran in a clean detached worktree at `7d0d86c` (`git status --porcelain`
was empty), on macOS with Python 3.11 and uv 0.13.5:

| Check | Result |
| --- | --- |
| `uv lock --check` | Resolved 49 packages |
| `python -m unittest discover -s tests` | Ran 1088 tests, OK (skipped=3) |
| `mypy atlas_core tests scripts/pinned_repo_review.py scripts/secret_scan_smoke.py` | No issues found in 128 source files |
| `pyright … scripts/reproducible_build.py` | 0 errors, 0 warnings |
| `pip-audit --strict --disable-pip --require-hashes -r <uv export --all-groups --no-emit-project>` | No known vulnerabilities found (45 packages) |
| `scripts/secret_scan_smoke.py` | detect-secrets detected and rejected the synthetic AWS canary |
| `detect-secrets-hook --baseline .secrets.baseline` over tracked files | Passed |

The audit can fail: a negative check with `filelock==4.0.3` reports
CVE-2026-112940, CVE-2026-112913 and CVE-2026-112907, and exits 1.

**SEC-01 probe at the pinned SHA.** The probe is a directory that git cannot
describe. Its `README.md` injects a finding with sound citations to
`docs/install.md`. The task is "Granska repots dokumentation: hur installerar
man projektet?". The run stops at `max_iterations` with no citation checks, and
`metadata.findings_sources` is `producer_section`. Before #151, the same probe
returned `passed` on iteration 1, at `83d7d2c` and at `v1.0.0`.

## Release bundle

Downloaded from run 40243597308 into an empty directory:

| File | SHA-256 (computed) | Manifest |
| --- | --- | --- |
| `atlas_core-1.1.0-py3-none-any.whl` | `07cd24ee7167faf412261ec2815c797241b6294a50667aa691a3bfceed1462bb` | matches |
| `atlas_core-1.1.0.tar.gz` | `7029cf15d6227814b7b78b2d74b163e7a51397836b8b431c3bf43571b45d1f6e` | matches |
| `atlas-core-1.1.0.cdx.json` | `0da19cef80eb25ca592a0c703db2c49143ba486d70155cb5b750a182dccc01f8` | matches |
| `release-integrity.json` | `f8837677bd9c696d7c2aaa124ff8d93ad2310cab721dd36a9de5e3ef5b89f796` | (the manifest) |

The manifest records:

- `source_commit`: `7d0d86c3ee88a8b2c62938d36d9fc77ae6fcfd58`
- `version`: `1.1.0`
- `source_date_epoch`: `1792969866`

**Local rebuild.** Running `scripts/reproducible_build.py` at the pinned SHA on
macOS reproduced the CI wheel and sdist digests. As before, the SBOM differs
only in its timestamp, serial number and the uv version it records. Its digest
binds the CI copy.

## Unchanged runtime files

`git diff --quiet v1.0.0 7d0d86c -- <file>` holds for:

- `cli.py`, `approval.py`, `tool_gateway.py`, `patch_proposal.py`, `machine.py`, `budget.py`, `worker_cli.py`
- `containment.py`, `integrity.py`, `redaction.py`
- `adapters/github_reader.py`, `adapters/_http.py`

These files under `atlas_core/` changed:

- `__init__.py` (version), `router.py`, `executor.py`, `controller.py`, `evaluator.py`, `observer.py`, `snapshot.py`, `evidence.py`, `claim_check.py`, `review_plan.py`, `review_producers.py`, `skill_generator.py`
- `adapters/filesystem_repo.py`, `adapters/live_model.py`, `adapters/model.py`, `adapters/output_contract.py`

That is 16 files, 1744 insertions and 87 deletions.

## Secrets baseline

`git diff v1.0.0 7d0d86c -- .secrets.baseline` moves six `line_number` values:

- #129 and #141: two
- #151: four, in `tests/test_evidence_in_the_loop.py` and `tests/test_structured_output.py`

No other field changes, and no entry is added.

## Hosting controls

Read through the GitHub REST API on 2026-10-26:

| Setting | Observed |
| --- | --- |
| Branch protection on `main` | A PR is required, with 0 required approvals and dismiss stale approvals on. Required checks are `python` and `python310`, strict. Enforced for admins. Force pushes and deletion are disabled |
| Rulesets | None |
| Collaborators | `MCamner` (admin) only |
| Secret scanning / push protection | Enabled / enabled |
| Non-provider patterns, validity checks | Disabled |
| Dependabot security updates | Disabled |
| GHSA-m8fx-mmrx-c449 | `draft`, not published |

**PR reviews.** GitHub records no review on any PR in the security gate,
including #151. Each was merged through `MCamner`. Reviews took place outside
GitHub (see [`README.md`](README.md#reviewer-independence)).
