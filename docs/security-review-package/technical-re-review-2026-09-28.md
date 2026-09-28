# Technical Re-review — Atlas Core v1.0.0

## Status

This is a **non-independent technical re-review** of the two blockers from
`docs/security-review-package/independent-review-2026-09-27.md`.

- Review target: `v1.0.0`
- Reviewed commit: `8230fecd3e7e4f4a0d65bb61ee517017d1857932`
- Review date: 2026-09-28
- Reviewer: OpenAI ChatGPT
- Independence status: **not independent**. This reviewer participated in
  later Atlas Core implementation/review work and therefore does not satisfy
  this repository's independent-review criterion.

The purpose of this report is to settle the **technical state** of F4/R11 and
C1 without misrepresenting the remaining governance requirement.

## Result

| Item | Technical result | Independent sign-off |
| --- | --- | --- |
| F4 / IR-1 / R11 | **Remediation effective** | Still required |
| C1 release bundle | **Satisfied** | Still required as part of gate sign-off |
| C5 independent re-review | Not satisfied by this report | **Open** |

No new blocking technical finding was identified in the scoped re-review of
`8230fec`.

## F4 / IR-1 / R11 — terminal approval boundary

### Original blocker

The original review found that an in-band terminal approval could be satisfied
by a process controlling the pseudo-terminal. That did not prove permission
from an actor outside the proposing process.

### Remediation reviewed

At `8230fec`, the public CLI calls `patch_proposal.propose(..., ask=None,
granted_by="external-authority")`. The CLI does not call `input()` or
otherwise collect an approval answer from stdin.

`patch_proposal.propose` treats `ask=None` as a hard stop:

- tests must pass first;
- an approval request is recorded;
- the function returns `outcome="approval_required"`;
- no grant token is issued;
- the write gateway is not invoked.

A write-capable embedding host may supply an `ask` callback, but the documented
contract requires that callback to use an approval channel the proposing
process cannot control. The public CLI itself ships no such grant path.

### Regression evidence

`tests/test_patch_proposal.py` at `8230fec` contains:

- `test_no_input_stops_at_approval_required_with_exit_3`;
- `test_a_terminal_controller_cannot_approve_its_own_write`.

The latter forces `sys.stdin.isatty() == True` and makes any call to
`builtins.input` fail the test. The CLI still returns exit 3,
`approval_required`, and leaves the repository untouched.

### Technical conclusion

**F4 / IR-1 / R11 is technically remediated for the public CLI boundary.**

The remaining `ask` callback is an explicit trusted-host boundary, not an
in-band CLI approval path. Core documents that a host which gives an agent
arbitrary shell/Git access is outside this control.

The documented "human-approved patch proposal" use case is therefore a
**host-integration contract**, not a claim that Atlas Core ships a standalone
approval UI. That distinction is explicit in
`examples/approved-patch-proposal.md`.

## C1 — published release-integrity bundle

### Release identity

GitHub reports:

- annotated tag: `v1.0.0`;
- tag verification: `verified: true`, reason `valid`;
- tag object target:
  `8230fecd3e7e4f4a0d65bb61ee517017d1857932`.

Exact-main workflow run `36315653280`:

- event: `push`;
- conclusion: `success`;
- `head_sha`:
  `8230fecd3e7e4f4a0d65bb61ee517017d1857932`.

### CI artifact

Artifact `atlas-core-release-integrity` from run `36315653280` contains:

| File | Size | SHA-256 |
| --- | ---: | --- |
| `atlas_core-1.0.0-py3-none-any.whl` | 207113 | `bc7d6bcc79cb1812d05e813ed192fa74fd9895e06812d426acf0488659fa074b` |
| `atlas_core-1.0.0.tar.gz` | 354136 | `6fe69c16f31f7f1ca1329e93b0590483c1ca1a952cf137929156246e86f5e9a9` |
| `atlas-core-1.0.0.cdx.json` | 1233 | `1600551aa287a3e3b4e146391e2c7b00a6700d628425d786510fa973350d6f7b` |
| `release-integrity.json` | 722 | `4323c1edc822805da424b21ec7a404337e9d7df85a0f92e8892a0b9a700535c9` |

The manifest inside that artifact states:

- schema: `atlas-release-integrity.v1`;
- package: `atlas-core`;
- version: `1.0.0`;
- source commit:
  `8230fecd3e7e4f4a0d65bb61ee517017d1857932`;
- wheel, sdist and SBOM digests equal the artifact bytes.

### Published release assets

The GitHub release for `v1.0.0` contains the same four files. GitHub's
asset metadata reports exactly the same sizes and SHA-256 digests listed
above.

Therefore the retained release bundle is byte-identical to the verified CI
artifact produced by exact-main run `36315653280`.

### Technical conclusion

**C1 is satisfied.**

The release tag is verified, resolves to the reviewed commit, the build run is
green on that exact commit, and the four retained release assets match the CI
artifact byte-for-byte.

## Overall technical conclusion

For the scoped blockers at `v1.0.0 / 8230fec`:

- F4 / IR-1 / R11: **closed technically**;
- C1: **closed technically**;
- new blocking technical findings in this scoped re-review: **none**.

This report does **not** satisfy C5's independence requirement and therefore
does not, by itself, authorize changing the roadmap Security checkbox to
`[x]`.

A separate reviewer who meets the independence requirement may use this report
and the linked evidence as input, but must reach and record their own
conclusion.
