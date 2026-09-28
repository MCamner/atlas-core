# Independent Security Re-review Closure — Atlas Core v1.0.0

## Reviewer

- Reviewer: ChatGPT (GPT-5.6 Sol), automated independent technical reviewer.
- Review date: 2026-09-28.
- Independence basis: this closure review evaluated repository evidence and the immutable release baseline independently of the author-side technical re-review. No Atlas Core code or remediation was authored as part of this review. This is an automated technical review, not a human assurance engagement.

## Reviewed target

- Release: `v1.0.0`
- Commit: `8230fecd3e7e4f4a0d65bb61ee517017d1857932`
- The annotated tag resolves to that exact commit.
- GitHub reports the tag signature as `verified: true`, reason `valid`.
- Runtime changes after this commit are outside this closure decision.

## Re-review scope

This report re-evaluates the two blockers from the independent review at
`5702aa7385efda8f9d893be036aee56fe4cf07be`:

1. IR-1 / F4 / R11 — terminal-controller approval could satisfy its own grant.
2. C1 — verified release artifacts were not retained on a release tag.

Other residual risks retain the dispositions from the original independent
review unless changed below.

## F4 / R11 re-review

The remediation in #109 is effective for the public CLI boundary.

- `atlas_core.cli._propose` calls `patch_proposal.propose(..., ask=None, ...)`.
- The CLI therefore cannot read an approval value from stdin or a pseudo-terminal.
- With `ask=None`, the proposal returns `approval_required` before any grant or
  write tool invocation.
- `tests/test_patch_proposal.py` contains the negative regression
  `test_a_terminal_controller_cannot_approve_its_own_write`.
- The separate Python API can still write only when a host supplies an `ask`
  callback. That host boundary is explicitly outside the proposing process and
  is the documented approval authority.

Decision: **F4 / R11 CLOSED.**

The security property established here is not that Atlas Core can authenticate
a human by itself. It is that the public proposing process cannot manufacture
its own approval, and that a write-capable host must supply authority through a
separate channel.

## C1 re-review

The release-publication condition is satisfied.

Exact-main workflow run `36315653280` completed successfully on
`8230fecd3e7e4f4a0d65bb61ee517017d1857932`.

The retained workflow artifact `atlas-core-release-integrity` was downloaded
and hashed during this re-review. Its files are:

| File | SHA-256 | Size |
| --- | --- | ---: |
| `atlas_core-1.0.0-py3-none-any.whl` | `bc7d6bcc79cb1812d05e813ed192fa74fd9895e06812d426acf0488659fa074b` | 207113 |
| `atlas_core-1.0.0.tar.gz` | `6fe69c16f31f7f1ca1329e93b0590483c1ca1a952cf137929156246e86f5e9a9` | 354136 |
| `atlas-core-1.0.0.cdx.json` | `1600551aa287a3e3b4e146391e2c7b00a6700d628425d786510fa973350d6f7b` | 1233 |
| `release-integrity.json` | `4323c1edc822805da424b21ec7a404337e9d7df85a0f92e8892a0b9a700535c9` | 722 |

GitHub's `v1.0.0` release exposes the same four assets with the same SHA-256
digests. The manifest identifies `source_commit` as the reviewed commit and
version `1.0.0`.

Decision: **C1 CLOSED.**

## Residual risks

The following remain non-blocking for this release baseline:

- R7: secret-baseline changes require disciplined human review.
- R12: proposal-repository Git configuration still has documented textconv /
  reference-transaction exposure in the caller-trusted repository.
- H1: branch protection requires no approving review.
- H2: Dependabot security updates are disabled while strict audit remains
  required.

These are follow-up governance/hardening items and do not invalidate the
reviewed `v1.0.0` security boundary.

## Scope boundary

This closure applies only to `v1.0.0` /
`8230fecd3e7e4f4a0d65bb61ee517017d1857932`.

Later runtime changes, including #112, #114, #116 and #119, are not covered by
this sign-off and require their own security review before a later release is
described as independently reviewed.

## Conclusion

- Blocking findings remaining for the reviewed baseline: **NO**.
- IR-1 / F4 / R11: **closed**.
- C1: **closed**.
- Independent security gate for Atlas Core `v1.0.0`: **APPROVED / READY TO CLOSE**.

The v2.0 security checklist item may be marked complete for this pinned release
baseline. This conclusion must not be generalized to later `main`.
