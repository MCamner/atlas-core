# Independent Security Review Package: v1.1.0

Repository: `MCamner/atlas-core`

Purpose: input for the independent security review in `ROADMAP.md`, P1 / v2.1,
box 5. The review covers every runtime and CI change after `v1.0.0` that the
next-release security gate names.

## What is being reviewed

| | |
| --- | --- |
| Release target | `v1.1.0` (not yet tagged) |
| Pinned release SHA | `83d7d2c12ddaf00454be2adfcb9ceb3a6223552d` |
| Previous reviewed baseline | `v1.0.0` / `8230fecd3e7e4f4a0d65bb61ee517017d1857932` |
| Review package revision | the later documentation commit that contains this package |

The code target is the pinned SHA. Later commits on `main`, including the one
that adds this package, do not move it. If a blocking finding is fixed, the fix
gets a new pinned SHA, and the re-review targets that SHA.

Verify the target before reading anything else:

```sh
git cat-file -t 83d7d2c12ddaf00454be2adfcb9ceb3a6223552d   # commit
git merge-base --is-ancestor v1.0.0 83d7d2c12ddaf00454be2adfcb9ceb3a6223552d && echo ancestor
git log --oneline v1.0.0..83d7d2c12ddaf00454be2adfcb9ceb3a6223552d | wc -l   # 31
```

## Status of this package

This package describes the changes and the evidence the authors collected.
**It is not a security approval.** The authors wrote the code and this package,
so nothing in it counts toward the conclusion. Each file separates three kinds
of statement:

- **Verified by the authors:** a fact with the command or run that shows it.
  The reviewer should re-check what matters to the conclusion.
- **Known risk:** a limit the authors know about. Listing it does not accept
  it.
- **For the reviewer:** a question the authors cannot settle themselves.

The conclusion is the reviewer's, written in
[`reviewer-report-template.md`](reviewer-report-template.md), as PASS, FAIL or
INSUFFICIENT EVIDENCE.

## Contents

| File | What it gives the reviewer |
| --- | --- |
| [`scope.md`](scope.md) | In and out of scope, trust boundaries, what changed in them since `v1.0.0` |
| [`changes.md`](changes.md) | All 31 commits from `v1.0.0` to the target, classified, with merge SHA, exact-main run and files |
| [`threat-model-delta.md`](threat-model-delta.md) | Each changed area: claim, code, tests, and the questions for the reviewer |
| [`evidence.md`](evidence.md) | CI runs, local checks at the target, release bundle digests, hosting controls |
| [`residual-risks.md`](residual-risks.md) | Limits carried from `v1.0.0` and new ones since |
| [`review-commands.md`](review-commands.md) | Commands to reproduce every check from a clean checkout |
| [`reviewer-report-template.md`](reviewer-report-template.md) | Structure for the independent conclusion |

## Reviewer independence

The rule from the `v1.0.0` package applies: the reviewer must not have written
Atlas Core code or this package, and must not have taken part in implementing
or reviewing the PRs under review. The report states the basis for
independence.

**Verified by the authors**, and relevant to that rule:

- GitHub records no PR reviews on any PR in the security gate. Every one is
  authored and merged through the single account `MCamner` (Dependabot is the
  author of #132, #133, #138, #139 and #140). See [`evidence.md`](evidence.md#hosting-controls).
- #141 to #148 were written by an AI coding agent (Claude Code) working for the
  maintainer. That agent also merged #144 and #146, and wrote this package.
- The maintainer's PR-level reviews of #141 to #149 were drafted with a
  separate AI assistant (ChatGPT). By its own reports, that assistant also
  merged #143, #145, #147 and #148 through the account.

Under the rule above, neither of those agents is independent for this review.
A reviewer who reviewed or merged any PR in the gate should say so in the
report, and the maintainer decides whether that review can close box 5.

## How findings are handled

- **Blocking findings** are fixed in a new PR, merged with green exact-main
  CI, and re-reviewed against the new pinned SHA.
- **Non-blocking findings** are recorded as residual risks with rationale,
  owner and follow-up.
- A finding is not accepted as a residual risk by the same person or agent
  that implemented the control it concerns.
- No new functionality is taken in while box 5 is open, and no tag or release
  is made until it passes.

## Existing material this package builds on

- [`../security-review-package/`](../security-review-package/): the `v1.0.0`
  package and its closed review. It applies to `8230fec` only.
- [`../security-review.md`](../security-review.md): the authors' internal review
- [`../safety-model.md`](../safety-model.md): enforced boundaries and their limits
- [`../api-contract.md`](../api-contract.md): public CLI, schemas and compatibility rules
- [`../release-checklist.md`](../release-checklist.md): what box 6 must do after a PASS
