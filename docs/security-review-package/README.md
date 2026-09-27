# Independent Security Review Package

Repository: `MCamner/atlas-core`

Purpose: input for the independent security review required by the Atlas Core
v2.0 exit gate (`ROADMAP.md`, P2 / v2.0, security item).

## What is being reviewed

| | |
| --- | --- |
| Code security baseline | `6474f17d4ca6fa75d56f29d2475ad4bfcb1c7d60` (`main`, 2026-09-27) |
| Review package revision | the `main` commit that contains this version of the package |

The code baseline is the last commit that changed code, workflows or
dependencies. It includes the fixes for the pre-review findings in
[`pre-review-findings.md`](pre-review-findings.md).

This package cannot name its own revision, because recording a SHA in it
creates a new commit. The reviewer records the `main` commit they reviewed
and confirms that nothing but documentation changed since the code baseline:

```sh
git diff --stat 6474f17d4ca6fa75d56f29d2475ad4bfcb1c7d60 <reviewed-commit> \
  -- atlas_core .github scripts pyproject.toml uv.lock
```

Empty output means the evidence in this package applies. If code changed,
review the later commit and treat the evidence here as applying only where
the reviewer confirms it still holds.

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
