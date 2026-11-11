# Residual Risks and Open Conditions

Pinned release SHA: `7d0d86c3ee88a8b2c62938d36d9fc77ae6fcfd58`

Listing a risk here does not accept it. For each item, the reviewer decides
whether it is acceptable, needs a fix, or blocks the release.

## Carried from `v1.0.0`

R1 to R12 and H1 to H2 in `../security-review-package/known-residual-risks.md`
concern code and settings that this release does not change. The exception is
R12, below. They are restated so that their state at the target is explicit:

| # | Limit | State at `7d0d86c` |
| --- | --- | --- |
| R1 | Core cannot make an external model ignore malicious text | Unchanged |
| R2 | A process boundary is not an OS sandbox | Unchanged |
| R3 | The in-process API and `--unsafe-legacy-unbounded` have no hard deadline | Unchanged |
| R4 | Windows fails closed for the bounded CLI | Unchanged |
| R5 | A directory component can be swapped for a link between resolve and open | Unchanged (`containment.py`, `integrity.py` untouched) |
| R6 | Redaction covers credential shapes, home paths and email only | Unchanged (`redaction.py` untouched) |
| R7 | A wrongly approved `.secrets.baseline` entry can hide a secret | No new entries since `v1.0.0`; two line numbers moved |
| R8 | `atlas propose --test` runs as the caller | Unchanged |
| R9 | `clean_head` checks HEAD and the worktree, not `ref` | Unchanged |
| R10 | Rollback is compare-and-swap only | Unchanged |
| R11 | Closed for `v1.0.0` | `cli.py`, `approval.py` and `patch_proposal.py` untouched |
| R12 | Git in observed repositories overrides only `core.fsmonitor` | `GIT_HARDENING` unchanged. The new CI E2E runs Atlas over a second repository (see N5) |
| H1 | 0 required approvals, single admin | Unchanged. Now also: no GitHub-recorded review on any gate PR (N7) |
| H2 | Dependabot security updates disabled | Unchanged. Vulnerability alerts also not enabled |

## New since `v1.0.0`

| # | Risk or limit | Source |
| --- | --- | --- |
| N1 | PyPI's `atlas-core` is an unrelated project (releases 1.0.0 and 1.2.0). `pip install atlas-core` installs that project. Before #146, CI's audit looked up that project's release instead of this package | #146, `CHANGELOG.md` v1.1.0 |
| N2 | A v1 findings reader skips an `atlas-findings.v2` block and does not see the relation finding. This is deliberate, and it is not full functional compatibility | #148, [`threat-model-delta.md`](threat-model-delta.md#4-the-findings-block-v1-and-v2-128-148) |
| N3 | SEC-01 (GHSA-m8fx-mmrx-c449). Repository text in the route output was read as findings and could make a run pass. Reproduced at `83d7d2c` and `v1.0.0`; fixed in #151. Residual: `v1.0.0` stays affected. The advisory is published (2026-10-26) and lists no patched version until `v1.1.0` is tagged | [`threat-model-delta.md`](threat-model-delta.md#5-sec-01-repository-text-and-the-findings-channel) |
| N4 | Deterministic producers use line-based parsing. Whether they engage depends on keywords in the task. Other wording stops without passing | #114, #116, #119, #127 |
| N5 | CI processes a second repository (mq-agent at a pinned commit) in the same job that later builds and uploads the release bundle | #127, `test.yml` |
| N6 | `docs/api-contract.md` ("only optional additive properties") and `contracts.COMPATIBILITY` ("add an enum member to a field whose absent value is already meaningful") state the compatibility rule differently. Neither allowed #128's change, and the texts have not been reconciled | #148 PR description |
| N7 | No PR in the gate has a GitHub-recorded review. Reviews were done outside GitHub, by the maintainer with AI assistants, and the same assistants merged several PRs | [`README.md`](README.md#reviewer-independence) |
| N8 | The release SBOM is not byte-reproducible across environments (timestamp, serial number, tool version). Wheel and sdist are | [`evidence.md`](evidence.md#release-bundle) |
| N10 | `adapter_output` fallback. When `ModelResult.findings_block` is `None`, the adapter's whole output is read as findings, so prose and findings are one text. This covers adapters that do not set it, `StubModelAdapter`, and `LiveModelAdapter` with `structured_output=False`. It is deprecated for 2.0 and recorded in `metadata.findings_sources` | #151, `docs/api-contract.md` |
| N11 | The SEC-01 fix had a documented technical review only. No independent approval is on record | [`README.md`](README.md#sec-01) |
| N9 | The `python310` job runs the unit tests only. Type checks, the audit and the release build run on 3.11.16 | #143, `docs/api-contract.md` support matrix |

## Open conditions for box 6 (after a PASS)

These come from `docs/release-checklist.md`. None of them is met yet.

| # | Condition |
| --- | --- |
| C1 | Annotated tag `v1.1.0` on the reviewed SHA, never moved |
| C2 | Wheel, sdist, SBOM and digest manifest from exact-main CI attached to the release, with digests verified after upload |
| C3 | Smoke-test install from the built wheel in a clean environment, and run the documented read-only example |
| C4 | Re-read the hosting controls when the review ends |
