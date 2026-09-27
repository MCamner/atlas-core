# Known Residual Risks and Open Conditions

Review target: `07ac3944db800b28bfc41fcd933cd10d6b04c00d`

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

## Hosting and process

| # | Condition | Source |
| --- | --- | --- |
| H1 | Branch protection requires 0 approvals; one account holds admin. | [`hosting-controls.md`](hosting-controls.md) |
| H2 | Dependabot security updates are disabled. | [`hosting-controls.md`](hosting-controls.md) |
| H3 | `run-atlas.yml` runs `pytest -q`, which stops at collection on the review target. | [`test-evidence.md`](test-evidence.md) |

## Release conditions still open in `docs/security-review.md`

`docs/security-review.md` lists these as conditions for marking the security
item complete, in addition to the independent review. They are not met at the
review target:

| # | Condition | State at review target |
| --- | --- | --- |
| C1 | Attach verified wheel, sdist, release SBOM and digest manifest from a passing main run to a release tag; retain the digests. | Not done. No GitHub release; only tag is `v0.2.0`. |
| C2 | Verify that Dependabot update PRs are reviewed. | Not verified. |
| C3 | Re-check that branch protection still requires `python`. | Holds as of the observation in [`hosting-controls.md`](hosting-controls.md). |
| C4 | Secret scan runs on PRs and main; canary retained. | `test.yml` runs on `pull_request` and `push` to `main`; canary step present. |
| C5 | Independent review of threat model, implementation and residual risks. | This package is the input; review not yet performed. |

The reviewer's report should say whether C1 and C2 must be met before the
security item closes, or can be tracked separately.
