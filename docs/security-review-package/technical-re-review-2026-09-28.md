# Technical Re-review Report — Atlas Core v1.0.0

Review target: `v1.0.0` / `8230fecd3e7e4f4a0d65bb61ee517017d1857932`

Review date: 2026-09-28

Reviewer role: technical re-review performed by ChatGPT with repository access and
independent reproduction of the two remaining blockers.

## Independence statement

This report is **not** an independent-security-review attestation under this
package's own independence rule. The reviewer has participated in later Atlas
Core implementation/review work and edited the security-review package in #111.
User authorization cannot change that factual relationship.

The report may therefore close the *technical findings* F4/R11 and C1, but it
does not by itself satisfy the separate v2.0 requirement that the closure
opinion be authored by a reviewer who meets the package's independence
criterion.

## Scope

This re-review is pinned to the immutable released target:

- tag: `v1.0.0`
- commit: `8230fecd3e7e4f4a0d65bb61ee517017d1857932`
- exact-main CI: run `36315653280`, event `push`, conclusion `success`,
  head SHA exactly `8230fecd3e7e4f4a0d65bb61ee517017d1857932`

Later runtime changes are out of scope for this v2.0 closure target.

## F4 / IR-1 / R11 — approval boundary

### Source review

At the target commit:

- `atlas_core/cli.py` calls `patch_proposal.propose(..., ask=None, ...)`.
  The public `atlas propose` command therefore has no path that reads an
  approval answer from stdin or grants an in-band terminal approval.
- `atlas_core/patch_proposal.py` treats `ask=None` as
  `approval_required` and performs no write.
- A write-capable embedding host may provide a trusted `ask` callback through
  a channel outside the proposing process.
- `tests/test_patch_proposal.py` includes both:
  - a negative pseudo-terminal test asserting the CLI cannot approve its own
    write; and
  - a positive host/API path where an exact external approval creates one
    `atlas/*` branch and leaves HEAD, the worktree and other refs unchanged.

### Independent runtime reproduction of target artifact

The wheel from exact-main run `36315653280` was installed with
`--no-deps`. It reports version `1.0.0`.

A fresh temporary git repository was then used for two reproductions:

1. **Public CLI under a pseudo-terminal**
   - command: `atlas propose ... --test true --json`
   - stdin/stdout attached to a PTY
   - no approval input supplied
   - exit code: `3`
   - outcome: `approval_required`
   - proposed branch created: **no**

2. **Write-capable host/API path**
   - `atlas_core.patch_proposal.propose` called with an explicit trusted
     callback returning the operation code after seeing the rendered proposal
   - outcome: `branch_created`
   - exactly the requested `atlas/*` branch was created
   - original HEAD stayed unchanged
   - worktree stayed clean
   - original checked-out file stayed unchanged

### F4 conclusion

**Resolved at `8230fec`.**

The original blocker was that an autonomous process controlling the same
terminal could read and submit its own approval. That path no longer exists in
the public CLI. Mutation requires a separate host-provided approval callback.

The v2.0 exit gate asks for a documented approved-patch-proposal use case; it
does not require Atlas Core itself to ship a standalone approval UI. The
documented use case remains demonstrated at the Core API boundary, while the
public CLI correctly remains proposal-only.

## C1 — retained release-integrity bundle

### Tag and commit binding

GitHub reports the annotated tag `v1.0.0` as signature-verified
(`verified: true`, reason `valid`). The tag resolves to:

`8230fecd3e7e4f4a0d65bb61ee517017d1857932`

The target commit is itself signature-verified. Its commit timestamp is
`1790508292`, which matches the `source_date_epoch` in the release manifest.

### Exact-main CI

Run `36315653280`:

- event: `push`
- status: completed
- conclusion: success
- head SHA: exactly
  `8230fecd3e7e4f4a0d65bb61ee517017d1857932`
- retained artifact: `atlas-core-release-integrity`

The downloaded CI artifact contains:

| File | SHA-256 |
| --- | --- |
| `atlas-core-1.0.0.cdx.json` | `1600551aa287a3e3b4e146391e2c7b00a6700d628425d786510fa973350d6f7b` |
| `atlas_core-1.0.0-py3-none-any.whl` | `bc7d6bcc79cb1812d05e813ed192fa74fd9895e06812d426acf0488659fa074b` |
| `atlas_core-1.0.0.tar.gz` | `6fe69c16f31f7f1ca1329e93b0590483c1ca1a952cf137929156246e86f5e9a9` |
| `release-integrity.json` | `4323c1edc822805da424b21ec7a404337e9d7df85a0f92e8892a0b9a700535c9` |

### Published GitHub release

The public `v1.0.0` GitHub release contains the same four named assets.
GitHub's recorded SHA-256 digest for each uploaded release asset is exactly the
same as the corresponding file hash calculated from the exact-main CI
artifact above.

The manifest in that artifact records:

- schema: `atlas-release-integrity.v1`
- package: `atlas-core`
- version: `1.0.0`
- source commit:
  `8230fecd3e7e4f4a0d65bb61ee517017d1857932`
- source date epoch: `1790508292`
- wheel/sdist digests and sizes matching the files
- release SBOM digest matching the file

The SBOM is CycloneDX 1.5 and identifies `atlas-core` version `1.0.0`.

### C1 conclusion

**Resolved.**

The verified bundle from the passing exact-main run is retained on the
`v1.0.0` release, with GitHub-recorded asset digests matching the independently
calculated hashes of the CI artifact.

## Blocking findings

Technical blocking findings remaining against
`v1.0.0` / `8230fec`: **NO**.

- F4 / IR-1 / R11: resolved.
- C1: resolved.

Previously documented non-blocking residual risks remain residual risks; this
re-review does not reclassify later post-v2.0 runtime changes.

## Closure status

Technical re-review result: **suitable for v2.0 security-gate closure on the
released baseline `v1.0.0` / `8230fec`, subject only to the separate
independence-attestation requirement.**

This report must **not** be used to state that current `main` has been
independently reviewed, and it must **not** by itself change the Security
checkbox to `[x]`.

A reviewer who satisfies the package's independence rule may adopt or challenge
this evidence, record their own conclusion, and then the docs-only closure PR
can mark the v2.0 security item complete.
