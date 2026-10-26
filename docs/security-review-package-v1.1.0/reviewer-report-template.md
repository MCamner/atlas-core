# Independent Security Review Report: Atlas Core v1.1.0

Copy this file and fill it in. Carry nothing over from the authors' material:
every conclusion below is the reviewer's own. FAIL and INSUFFICIENT EVIDENCE
are as valid as PASS.

## Reviewer

- Name:
- Organisation or role:
- Independence basis: your relation to the authors, and whether you implemented, reviewed or merged any PR in the gate (#112, #114, #116, #119, #127, #128, #129, #132, #133, #134, #137, #138, #139, #140, #142, #143, #146, #147, #148, #151):
- Review dates:
- Reviewed SHA (must be `7d0d86c3ee88a8b2c62938d36d9fc77ae6fcfd58` unless a re-review names a new one):
- How the SHA was verified:
- Material used (this package, source, CI logs, other):
- Methods (code reading, tests run, tooling, time spent):

## Scope

- Areas reviewed:
- Areas not reviewed, and why:
- Deviations from [`scope.md`](scope.md):

## Findings

For each finding, give:
- ID, title and severity
- affected files or settings
- description
- evidence or reproduction
- recommendation
- whether it blocks the release

### Critical

### High

### Medium

### Low

### Observations (no severity)

## Questions from the authors

Answer or decline each of the questions numbered 1–14 in
[`threat-model-delta.md`](threat-model-delta.md).

1.
2.
3.
4.
5.
6.
7.
8.
9.
10.
11.
12.
13.
14.

## The v1/v2 findings boundary (required)

ROADMAP v2.1 box 5 requires this to be tested explicitly. For each check, give the method and the result:

- A v1 reader skips an `atlas-findings.v2` block:
- A `command_targets_differ` in an `atlas-findings` block is refused:
- The model path cannot state `command_targets_differ`:

## SEC-01 (required)

GHSA-m8fx-mmrx-c449, fixed in #151. For each check, give the method and the result:

- Observed repository text cannot be graded as a finding, in a directory git cannot describe, in a git repository, and when git fails to resolve:
- A fence in a model's `report` does not displace or add to its `findings`:
- After a sent schema, a non-conforming reply states no findings:
- `evaluate()` cannot be called without a findings source:
- The `adapter_output` fallback (N10): acceptable for 1.1 / needs fix / blocking, and why:

## Residual risks

For each item in [`residual-risks.md`](residual-risks.md) (R1–R12, H1–H2, N1–N11), mark it acceptable, needs fix or blocking, with a short reason.

## Accepted residual risks

For each, give:
- the risk
- the rationale
- the recommended owner
- the follow-up and its date

The owner who accepts a risk must not be the person or agent who implemented the control it concerns.

## Conclusion

- Verdict: PASS / FAIL / INSUFFICIENT EVIDENCE
- Blocking findings remaining: YES / NO
- If FAIL: the blocking findings, by ID
- If INSUFFICIENT EVIDENCE: what is missing, and what would settle it
- Conditions attached to a PASS, if any:
- The verdict applies to `7d0d86c3ee88a8b2c62938d36d9fc77ae6fcfd58` only.

Signature / date:
