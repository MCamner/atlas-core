# Independent Security Review Package: v1.1.0

Repository: `MCamner/atlas-core`

Purpose: input for the independent security review in `ROADMAP.md`, P1 / v2.1,
box 5. The review covers every runtime and CI change after `v1.0.0` that the
next-release security gate names, including the SEC-01 fix.

## What is being reviewed

| | |
| --- | --- |
| Release target | `v1.1.0` (not yet tagged) |
| Pinned release SHA | `7d0d86c3ee88a8b2c62938d36d9fc77ae6fcfd58` |
| Superseded candidate | `83d7d2c12ddaf00454be2adfcb9ceb3a6223552d`, not to be released (SEC-01) |
| Previous reviewed baseline | `v1.0.0` / `8230fecd3e7e4f4a0d65bb61ee517017d1857932` |
| Review package revision | the later documentation commit that contains this package |

The code target is the pinned SHA. Later commits on `main`, including the one
that adds this package, do not move it. If a blocking finding is fixed, the fix
gets a new pinned SHA and the re-review targets that.

Verify the target first:

```sh
git cat-file -t 7d0d86c3ee88a8b2c62938d36d9fc77ae6fcfd58   # commit
git merge-base --is-ancestor v1.0.0 7d0d86c3ee88a8b2c62938d36d9fc77ae6fcfd58 && echo ancestor
git log --oneline v1.0.0..7d0d86c3ee88a8b2c62938d36d9fc77ae6fcfd58 | wc -l   # 35
```

## SEC-01

The preparatory security work for box 5 found SEC-01 (GHSA-m8fx-mmrx-c449).
Repository text that reached the route output could be read as a producer's
findings and make a `repo_review` run pass. The same holds for `v1.0.0`. The
fix is #151 (`85e2a23`), and #152 carries it into the v1.1.0 notes. Before the
merge, the fix had a documented technical review of `3fe0687`. **No independent
approval of the fix is documented.** This review is where that happens. See
[`threat-model-delta.md`](threat-model-delta.md#5-sec-01-repository-text-and-the-findings-channel).

## Status of this package

This package describes the changes and the evidence the authors collected.
**It is not a security approval.** The authors wrote the code and this package,
so nothing in it counts toward the conclusion. Each file separates three kinds
of statement:

- **Verified by the authors:** a fact, with the command or run that shows it.
- **Known risk:** a limit the authors know about. Listing it does not accept it.
- **For the reviewer:** a question the authors cannot settle themselves.

The conclusion is the reviewer's, written in
[`reviewer-report-template.md`](reviewer-report-template.md) as PASS, FAIL or
INSUFFICIENT EVIDENCE.

## Contents

| File | What it gives the reviewer |
| --- | --- |
| [`scope.md`](scope.md) | In and out of scope, trust boundaries, and what changed in them since `v1.0.0` |
| [`changes.md`](changes.md) | All 35 commits from `v1.0.0` to the target, classified, with merge SHA, exact-main run and files |
| [`threat-model-delta.md`](threat-model-delta.md) | Each changed area: claim, code, tests, and questions for the reviewer |
| [`evidence.md`](evidence.md) | CI runs, local checks at the target, release bundle digests, hosting controls |
| [`residual-risks.md`](residual-risks.md) | Limits carried from `v1.0.0`, and new ones since |
| [`review-commands.md`](review-commands.md) | Commands to reproduce every check from a clean checkout |
| [`reviewer-report-template.md`](reviewer-report-template.md) | Structure for the independent conclusion |

## Reviewer independence

The rule from the `v1.0.0` package applies. The reviewer must not have written
Atlas Core code or this package, and must not have taken part in implementing
or reviewing the PRs under review. The report states the basis for
independence.

**Verified by the authors**, and relevant to that rule:

- GitHub records no PR review on any PR in the security gate. Every PR was
  merged through the single account `MCamner`. Dependabot is the author of
  #132, #133, #138, #139 and #140. See [`evidence.md`](evidence.md#hosting-controls).
- An AI coding agent working for the maintainer (Claude Code) wrote #141 to
  #152. That agent also merged #144, #146, #151 and #152, and it wrote this
  package.
- The maintainer drafted the PR-level reviews of #141 to #152, and the SEC-01
  patch review, with a separate AI assistant (ChatGPT). By its own reports,
  that assistant merged #143, #145, #147 and #148 through the account.

Under the rule above, neither agent is independent for this review.

## How findings are handled

- A **blocking finding** is fixed in a new PR that is merged with green
  exact-main CI. The fix is then re-reviewed against the new pinned SHA.
- A **non-blocking finding** is recorded as a residual risk, with rationale,
  owner and follow-up.
- A finding is not accepted as a residual risk by the same person or agent who
  implemented the control it concerns.
- While box 5 is open, no new functionality goes in and no tag or release is
  made.

## Existing material this package builds on

- [`../security-review-package/`](../security-review-package/): the `v1.0.0` package and its closed review. It applies to `8230fec` only.
- [`../security-review.md`](../security-review.md), [`../safety-model.md`](../safety-model.md), [`../api-contract.md`](../api-contract.md), [`../release-checklist.md`](../release-checklist.md)
