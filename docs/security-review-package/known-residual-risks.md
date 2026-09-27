# Known Residual Risks and Open Conditions

Code security baseline: `6474f17d4ca6fa75d56f29d2475ad4bfcb1c7d60`

These are limits the authors already know about. Listing them here does not
accept them. The reviewer decides whether each is acceptable, needs a fix, or
blocks closure.

## Documented limits of the implementation

| # | Limit | Where documented |
| --- | --- | --- |
| R1 | Core cannot make an external model ignore malicious repository or tool text. | `docs/safety-model.md`, `docs/security-review.md` |
| R2 | A process boundary is not an OS sandbox. Trusted adapters and tool handlers run with the caller's privileges and can use the filesystem and network directly. | `docs/safety-model.md` |
| R3 | The in-process Python API, embedded `main([...])` and `--unsafe-legacy-unbounded` have cooperative or no hard deadline. | `docs/safety-model.md` |
| R4 | Windows fails closed for the bounded CLI and `run_isolated`; there is no Job Object implementation. | `docs/safety-model.md` |
| R5 | A directory component of a read path can be replaced by a symlink between resolve and open. | `atlas_core/integrity.py` docstring |
| R6 | Redaction covers credential shapes, home directories and email addresses only. | `atlas_core/redaction.py`, `docs/safety-model.md` |
| R7 | A wrongly approved `.secrets.baseline` entry can hide a real secret. | `docs/security-review.md` |
| R8 | The `atlas propose --test` command runs as the caller without a sandbox. | `docs/security-review.md` |
| R9 | `clean_head` checks HEAD and a clean worktree, not where `ref` points; each write use case must enforce the base itself. | `docs/safety-model.md` |
| R10 | Rollback in `atlas propose` removes the branch only if it still points to Core's commit; process termination does not undo side effects already committed. | `atlas_core/patch_proposal.py`, `docs/safety-model.md` |
| R11 | Fixed after the review baseline: the public CLI never reads or grants terminal approval and always stops at `approval_required`. Write-capable hosts must keep the approval channel outside the proposing process. | [`pre-review-findings.md`](pre-review-findings.md), `docs/safety-model.md`, `docs/api-contract.md` |
| R12 | Git runs in observed and target repositories with only `core.fsmonitor` overridden. In `atlas propose`, the caller's own repository can still run a textconv driver during `git diff` and a `reference-transaction` hook during `update-ref`. | [`pre-review-findings.md`](pre-review-findings.md) (F1) |

## Hosting and process

| # | Condition | Source |
| --- | --- | --- |
| H1 | Branch protection requires 0 approvals; one account holds admin. | [`hosting-controls.md`](hosting-controls.md) |
| H2 | Dependabot security updates are disabled. | [`hosting-controls.md`](hosting-controls.md) |
| H3 | Fixed: `run-atlas.yml` ran `pytest -q`, which stopped at collection. It now runs `unittest discover` (#99). | [`pre-review-findings.md`](pre-review-findings.md) |

## Release conditions still open in `docs/security-review.md`

`docs/security-review.md` lists these as conditions for marking the security
item complete, in addition to the independent review. State at the code
baseline:

| # | Condition | State |
| --- | --- | --- |
| C1 | Attach verified wheel, sdist, release SBOM and digest manifest from a passing main run to a release tag; retain the digests. | Done. `v1.0.0` points to `8230fecd`; exact-main run 36315653280 passed and the four release assets retain matching SHA-256 digests. See [`release-integrity.md`](release-integrity.md). |
| C2 | Verify that Dependabot update PRs are reviewed. | Verified for the reviewed update: PR #93 records maintainer review and passed exact-head CI. |
| C3 | Re-check that branch protection still requires `python`. | Holds as of the observation at `6474f17` in [`hosting-controls.md`](hosting-controls.md). |
| C4 | Secret scan runs on PRs and main; canary retained. | `test.yml` runs on `pull_request` and `push` to `main`; canary step present. |
| C5 | Independent review of threat model, implementation and residual risks. | Performed in [`independent-review-2026-09-27.md`](independent-review-2026-09-27.md). Its F4 finding was remediated in #109 and awaits independent re-review. |

The reviewer's report should say whether C1 and C2 must be met before the
security item closes, or can be tracked separately.
