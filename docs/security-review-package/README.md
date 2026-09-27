# Independent Security Review Package

Repository: `MCamner/atlas-core`

Review target: `07ac3944db800b28bfc41fcd933cd10d6b04c00d` (`main`, 2026-09-27)

Purpose: input for the independent security review required by the Atlas Core
v2.0 exit gate (`ROADMAP.md`, P2 / v2.0, security item).

## Status of this package

This package describes the existing implementation and the evidence the
authors have collected. **It is not a security approval.** The authors wrote
both the code and this package, so nothing in it counts toward the review
conclusion. The conclusion must be written independently in
[`reviewer-report-template.md`](reviewer-report-template.md) or an equivalent
report.

If relevant code on `main` changes before the review starts, review the later
commit and bind the report to that SHA. The evidence in this package then
applies only where the reviewer confirms it still holds.

## Contents

| File | What it gives the reviewer |
| --- | --- |
| [`scope.md`](scope.md) | What is in and out of scope, trust boundaries, entry points |
| [`threat-model-map.md`](threat-model-map.md) | Each threat area mapped to code, tests and documented limits |
| [`test-evidence.md`](test-evidence.md) | CI run on the review target and how to reproduce it |
| [`release-integrity.md`](release-integrity.md) | Reproducible build, digests and SBOM for the review target |
| [`hosting-controls.md`](hosting-controls.md) | GitHub branch protection and repository security settings as observed |
| [`known-residual-risks.md`](known-residual-risks.md) | Limits the authors already know about, and open release conditions |
| [`reviewer-report-template.md`](reviewer-report-template.md) | Structure for the independent conclusion |

## Reviewer independence

The reviewer must not have written Atlas Core code, `docs/security-review.md`,
or this package, and must not have taken part in implementing or reviewing
PRs #87, #95, #96 or #97. The report states the basis for independence.

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
