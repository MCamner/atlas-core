# Changes Since the Independent Review

The independent review in
[`independent-review-2026-09-27.md`](independent-review-2026-09-27.md)
covered `main` at `5702aa7385efda8f9d893be036aee56fe4cf07be`. Its conclusion
was **not suitable** for closure, with two blockers: IR-1/F4/R11 and C1.

## Re-review target

| | |
| --- | --- |
| Release | [`v1.0.0`](https://github.com/MCamner/atlas-core/releases/tag/v1.0.0) (annotated tag; GitHub reports its signature as verified) |
| Commit | `8230fecd3e7e4f4a0d65bb61ee517017d1857932` |

Purpose: re-review the F4 remediation and the remaining v2.0 security-gate
conditions against the immutable released baseline. The target is the tagged
commit, because it contains the F4 remediation and the C1 release artifacts
were built from it.

**Changes after this baseline are outside this closure review.** A passed
re-review verifies the v2.0 security gate against `v1.0.0` / `8230fec` only;
it does not make later `main` independently reviewed. Later code is listed
under [Post-v2.0 changes](#post-v20-changes-outside-this-closure-review).

This file lists what reached `main` between the reviewed commit and the
target, so the re-review can start from the delta:

```sh
git rev-parse 'v1.0.0^{commit}'   # 8230fecd3e7e4f4a0d65bb61ee517017d1857932
git log --format='%h %s' 5702aa7385efda8f9d893be036aee56fe4cf07be..8230fecd3e7e4f4a0d65bb61ee517017d1857932
git diff --stat 5702aa7385efda8f9d893be036aee56fe4cf07be 8230fecd3e7e4f4a0d65bb61ee517017d1857932 \
  -- atlas_core .github scripts pyproject.toml uv.lock tests
```

"Main CI" is the `test` workflow `push` run on exactly the merge commit.

## Runtime code: F4 remediation (needs independent re-review)

| PR | Merge | Main CI | Change |
| --- | --- | --- | --- |
| [#109](https://github.com/MCamner/atlas-core/pull/109) | `8230fec` | [36315653280](https://github.com/MCamner/atlas-core/actions/runs/36315653280) | `atlas propose` CLI always passes `ask=None`; it never reads stdin for approval and cannot write. `--no-input` kept as a no-op for compatibility. |

- Files: `atlas_core/cli.py`, `atlas_core/patch_proposal.py` (docstring),
  `tests/test_patch_proposal.py`
  (`test_a_terminal_controller_cannot_approve_its_own_write`), plus
  `docs/api-contract.md`, `docs/safety-model.md`,
  `examples/approved-patch-proposal.md`.
- The same PR recorded the review. The reviewer implemented this
  remediation, so the report itself states it is not independently
  re-reviewed.
- Author-side check (not independent): the pseudo-terminal reproduction from
  [`pre-review-findings.md`](pre-review-findings.md#f4--terminal-approval-does-not-prove-a-human-approver)
  was re-run against `8230fec`. Result: `approval_required`, no branch
  created.
- Consequence for the exit gate: the only write path left is
  `atlas_core.patch_proposal.propose` with an `ask` callback supplied by a
  host. Core ships no such host or approval channel. The re-review should
  decide whether the documented use case "godkänt patchförslag" in
  `examples/approved-patch-proposal.md` is still demonstrated without one.

## CI and development dependencies

No runtime code or runtime dependency changed. Each PR was reviewed with a
comment review (not an approval) that records the checks below. New action
pins were checked against the tag's commit through the GitHub API.

| PR | Merge | Main CI | Change | Verified after merge |
| --- | --- | --- | --- | --- |
| [#94](https://github.com/MCamner/atlas-core/pull/94) | `d1e7391` | [36314260678](https://github.com/MCamner/atlas-core/actions/runs/36314260678) | mypy 2.1.0 → 2.3.1 (dev) | mypy/pyright clean in main CI |
| [#92](https://github.com/MCamner/atlas-core/pull/92) | `5a79def` | [36314391550](https://github.com/MCamner/atlas-core/actions/runs/36314391550) | actions/checkout 4.2.2 → 7.0.1 | see #90 and Pages rows |
| [#90](https://github.com/MCamner/atlas-core/pull/90) | `671a726` | [36314560000](https://github.com/MCamner/atlas-core/actions/runs/36314560000) | actions/setup-python 5.6.0 → 7.0.0 | `run-atlas.yml` on `671a726`: [36314624847](https://github.com/MCamner/atlas-core/actions/runs/36314624847) success |
| [#88](https://github.com/MCamner/atlas-core/pull/88) | `7fb6d17` | [36314719074](https://github.com/MCamner/atlas-core/actions/runs/36314719074) | actions/upload-pages-artifact 3 → 5.0.0 | Pages deploy [36314719065](https://github.com/MCamner/atlas-core/actions/runs/36314719065) success |
| [#89](https://github.com/MCamner/atlas-core/pull/89) | `67bb95c` | [36314817802](https://github.com/MCamner/atlas-core/actions/runs/36314817802) | actions/deploy-pages 4 → 5.0.1 | Pages deploy [36314817809](https://github.com/MCamner/atlas-core/actions/runs/36314817809) success |
| [#91](https://github.com/MCamner/atlas-core/pull/91) | `b256b50` | [36314924932](https://github.com/MCamner/atlas-core/actions/runs/36314924932) | actions/configure-pages 5 → 6.0.0 | Pages deploy [36314924968](https://github.com/MCamner/atlas-core/actions/runs/36314924968) success |

`pages.yml` does not run on pull requests, so the Pages rows are verified only
by the deploy on `main`. `upload-pages-artifact` v4+ excludes dotfiles;
`docs/` contains none.

## Release: C1

| PR | Merge | Change |
| --- | --- | --- |
| [#110](https://github.com/MCamner/atlas-core/pull/110) | `5eff78b` | Documentation only, after the target. Records release [`v1.0.0`](https://github.com/MCamner/atlas-core/releases/tag/v1.0.0) in [`release-integrity.md`](release-integrity.md#published-release). |

- Annotated tag `v1.0.0` resolves to `8230fec`, the #109 merge commit.
- Author-side check (not independent), done after publication:
  - The four release assets were downloaded and compared with the
    `atlas-core-release-integrity` artifact of main run
    [36315653280](https://github.com/MCamner/atlas-core/actions/runs/36315653280)
    (`push`, exactly `8230fec`, success). All four are byte-identical.
  - `release-integrity.json`: `source_commit` is `8230fec`;
    `source_date_epoch` `1790508292` equals the commit timestamp; wheel and
    sdist SHA-256 and sizes, and the SBOM SHA-256, match the files.
  - The SBOM is CycloneDX 1.5 for `atlas-core` `1.0.0`.
  - The release wheel installs with `--no-deps` into a clean Python 3.11.16
    virtual environment. `atlas version` prints `1.0.0`, and a read-only
    `atlas run --repo-path` finishes `done` / `passed`.

## Status of the review's blockers

- **F4/R11:** remediation merged in #109; non-independent technical re-review on 2026-09-28 found the fix effective at `8230fec`; independent sign-off still pending.
- **C1:** release `v1.0.0` published with the verified bundle (#110); non-independent technical re-review confirmed the release assets are byte-identical to the exact-main CI artifact.

## Post-v2.0 changes outside this closure review

These reached `main` after `v1.0.0`. They change runtime code and have no
independent security review. They are excluded from the v2.0 security
closure and form the security review backlog for the next release.

| PR | Merge | Main CI | Scope | Status |
| --- | --- | --- | --- | --- |
| [#112](https://github.com/MCamner/atlas-core/pull/112) `fix(router)` | `65c944a` | [36337962790](https://github.com/MCamner/atlas-core/actions/runs/36337962790) | `atlas_core/router.py`, `tests/test_router.py` | Excluded from v2.0 closure; review required before next release |
| [#114](https://github.com/MCamner/atlas-core/pull/114) `feat(review)` | `c04eb6a` | [36338784552](https://github.com/MCamner/atlas-core/actions/runs/36338784552) | deterministic CI review in `controller.py` / `executor.py` plus tests | Excluded from v2.0 closure; review required before next release |
| [#116](https://github.com/MCamner/atlas-core/pull/116) `feat(review)` | `bcdce6d` | [36347624268](https://github.com/MCamner/atlas-core/actions/runs/36347624268) | deterministic review-producer registry and bounded package-version metadata review | Excluded from v2.0 closure; review required before next release |
| [#119](https://github.com/MCamner/atlas-core/pull/119) `feat(evidence)` | `3d2fb4d` | [36351871876](https://github.com/MCamner/atlas-core/actions/runs/36351871876) | targeted line-range observations, reframed-evidence semantics and changelog version review | Excluded from v2.0 closure; review required before next release |

At the time this package was refreshed, `main` was
`3d2fb4dbf3ee7cbed0047b026299961f721a2ecb`. That fact is recorded only to
bound the backlog; it does not move the closure target away from
`v1.0.0` / `8230fec`.

Documentation commits after the target (#110, #111 and later package-only
updates) describe the target and do not change it.
