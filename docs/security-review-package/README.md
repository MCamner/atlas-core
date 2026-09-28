# Independent Security Review Package

Repository: `MCamner/atlas-core`

Purpose: input for the independent security review required by the Atlas Core
v2.0 exit gate (`ROADMAP.md`, P2 / v2.0, security item).

## What is being reviewed

| | |
| --- | --- |
| Release target | `v1.0.0` |
| Code security baseline | `8230fecd3e7e4f4a0d65bb61ee517017d1857932` |
| Review package revision | the later documentation commit that contains this package |

The security-gate re-review is intentionally pinned to the immutable released
baseline `v1.0.0` / `8230fec`. GitHub reports the annotated tag signature as
verified, and the tag resolves to that commit. This target contains the F4
remediation from #109 and is the source commit for the published v1.0.0 release.

The package itself may be updated later to describe evidence or later work.
Those documentation commits do **not** move the code target. Runtime changes
after `8230fec` are outside the v2.0 closure review and are listed in
[`changes-since-review.md`](changes-since-review.md).

The reviewer should first verify the immutable target and then inspect the
delta from the original independent review:

```sh
git rev-parse 'v1.0.0^{commit}'
# expected: 8230fecd3e7e4f4a0d65bb61ee517017d1857932

git log --format='%h %s' \
  5702aa7385efda8f9d893be036aee56fe4cf07be..8230fecd3e7e4f4a0d65bb61ee517017d1857932

git diff --stat \
  5702aa7385efda8f9d893be036aee56fe4cf07be \
  8230fecd3e7e4f4a0d65bb61ee517017d1857932 \
  -- atlas_core .github scripts pyproject.toml uv.lock tests
```

A passed re-review applies to `v1.0.0` / `8230fec` only. It must not be
described as an independent review of the later `main` branch.

## Status of this package

This package describes the implementation and the evidence the authors have
collected. **It is not a security approval.** The authors wrote the code, the
fixes and this package, so nothing in it counts toward the review conclusion.
The conclusion must be written independently in
[`reviewer-report-template.md`](reviewer-report-template.md) or an
equivalent report.

## Contents

| File | What it gives the reviewer |
| --- | --- |
| [`scope.md`](scope.md) | What is in and out of scope, trust boundaries, entry points |
| [`threat-model-map.md`](threat-model-map.md) | Each threat area mapped to code, tests and documented limits |
| [`pre-review-findings.md`](pre-review-findings.md) | Findings from the non-independent pre-review, with fix evidence; F4 open |
| [`test-evidence.md`](test-evidence.md) | CI run on the code baseline and how to reproduce it |
| [`release-integrity.md`](release-integrity.md) | Reproducible build, digests and SBOM for the code baseline |
| [`hosting-controls.md`](hosting-controls.md) | GitHub branch protection and repository security settings as observed |
| [`known-residual-risks.md`](known-residual-risks.md) | Limits the authors know about, and open release conditions |
| [`reviewer-report-template.md`](reviewer-report-template.md) | Structure for the independent conclusion |
| [`technical-re-review-2026-09-28.md`](technical-re-review-2026-09-28.md) | Non-independent technical re-review: F4/R11 and C1 are technically closed at `v1.0.0` / `8230fec`; C5 remains open |
| [`independent-review-2026-09-27.md`](independent-review-2026-09-27.md) | Independent review at `5702aa7`; closure refused on F4 and C1 |
| [`changes-since-review.md`](changes-since-review.md) | Re-review target `v1.0.0` / `8230fec`, the delta since `5702aa7`, and later changes excluded from v2.0 closure |

## Reviewer independence

The reviewer must not have written Atlas Core code, `docs/security-review.md`,
or this package, and must not have taken part in implementing or reviewing
PRs #87, #95–#106. The report states the basis for independence.

## How findings are handled

- **Blocking findings** are fixed and re-reviewed before the security item
  can close.
- **Non-blocking findings** are recorded as residual risks with rationale,
  owner and any follow-up.
- A finding is not accepted as a residual risk by the same person who
  implemented the control it concerns.

The security item in `ROADMAP.md` stays `[ ]` until the independent report
exists and states that no blocking findings remain.

## Existing material this package builds on

- [`../security-review.md`](../security-review.md): the authors' internal review
- [`../safety-model.md`](../safety-model.md): enforced boundaries and their limits
- [`../api-contract.md`](../api-contract.md): public CLI and write boundary
- [`../evidence/`](../evidence/): observed hosting and release evidence
