# Independent Security Review Report — Atlas Core

## Reviewer

- Name: OpenAI Codex
- Organisation / role: automated independent code reviewer
- Independence basis: this reviewer did not write Atlas Core, the internal
  security review, this review package, or PRs #87 and #95–#106, and did not
  participate in their implementation or prior review. This is an independent
  technical review, not a human assurance engagement.
- Review date: 2026-09-27
- Reviewed `main` commit: `5702aa7385efda8f9d893be036aee56fe4cf07be`
- Changes since code baseline `6474f17`: `pyproject.toml` and `uv.lock` update
  the CI-only `pytest` pin from 9.0.3 to 9.1.1. No package, workflow, script or
  runtime dependency changed. Exact-head CI run 36314160707 passed.
- Material used: the complete review package, linked internal security and
  safety documents, relevant source and regression tests, current GitHub
  branch-protection/security settings, PR #93, tags and Actions status.
- Methods: manual source and configuration review; comparison with the stated
  baseline; adversarial review of trust boundaries and residual risks; local
  execution of `uv run --locked --group ci python -m unittest discover -s
  tests` (1021 tests, 3 skipped, pass); verification of exact-head CI and
  current hosting settings.

## Scope

- Areas reviewed: all areas in [`scope.md`](scope.md), with emphasis on prompt
  injection, capability enforcement, approvals and writes, path containment,
  Git invocation, credentials and redirects, response/output bounds, CI,
  dependency locking, SBOM/reproducible-build controls and hosting settings.
- Areas not reviewed: external model correctness, third-party/host adapters,
  organisation/account security, and OS sandboxing. These are outside the
  declared product boundary. Artifact bytes from the expiring baseline run
  were not independently rebuilt or downloaded in this review.
- Deviations from `scope.md`: none. The later CI-only dependency update was
  additionally reviewed so the conclusion applies to current `main`.

## Findings

### Critical

None.

### High

None.

### Medium

#### IR-1 — In-band terminal approval does not prevent autonomous mutation

Remediation was subsequently added on this branch: the public CLI always
passes `ask=None`, never consults stdin for approval and therefore cannot
write. A negative terminal-controller regression test covers this boundary.
Because this reviewer implemented that remediation, this note is not an
independent re-review and the fix must be re-reviewed before closure.

- Affected: `atlas_core/patch_proposal.py` (`render`, `propose`), CLI terminal
  check, and the v2.0 exit condition.
- Description: the approval value is derived from and printed with the
  operation. A process controlling a pseudo-terminal can read it and submit it
  without an independent actor. The operation binding, expiry, one-time token,
  compare-and-swap write and post-write verification are effective, but they
  prove approval by the terminal controller, not permission from outside an
  autonomous agent.
- Evidence: F4's reproduction is consistent with the reviewed code. The test
  helper in `tests/test_patch_proposal.py` also demonstrates that a callback
  can derive the answer from the rendered operation and cause branch creation.
- Recommendation: require a grant through a channel unavailable to the
  proposing process, or narrow the v2.0 claim and enforce agents' no-input mode
  at a boundary the agent cannot override. Add a negative end-to-end test in
  which a process controlling stdin/stdout cannot issue its own grant.
- Closure: **blocking**. The current mechanism does not satisfy the unqualified
  exit condition “Ingen autonom mutation utan tillstånd.”

### Low

None newly identified.

### Observations

#### IR-O1 — Release evidence is generated but not retained with a release

The reproducible-build and SBOM mechanisms are credible and CI-gated, but the
baseline artifacts remain an expiring Actions artifact. No release contains
the wheel, sdist, release SBOM and digest manifest. This is C1, not a new code
defect, but it independently prevents the documented security item from
closing.

## Pre-review findings

- F1: fix effective for the observed-repository `rev-parse`/`status` path.
  High is reasonable because repository-controlled configuration previously
  crossed the read-only boundary into command execution. The narrower Git
  configuration exposure in R12 remains.
- F2: fix effective against terminal control and format characters. High is
  reasonable because the approval display is a security boundary. Homoglyphs,
  long lines and scrollback exhaustion remain presentation risks.
- F3: fix effective. Medium is reasonable. Origin comparison includes scheme,
  host and port and removes `Authorization` on change.
- F4: reproducible from the design and **blocking**, as IR-1. Medium.
- F5: fix effective. Low is reasonable; the 16 MiB body bound is conservative
  but finite, and parsing occurs only after the bounded read.
- F6: fix effective for the named shapes. Low is reasonable. Pattern-based
  redaction remains incomplete by design and must not be treated as a DLP
  guarantee.
- O1: fix effective. Observation severity is appropriate; the fixed API host
  prevented a cross-origin consequence.

## Questions from the authors

1. Yes. Refusing `.` and `..`, applying the owner/name grammar and keeping the
   API origin fixed is sufficient for the stated reader surface.
2. The endpoint and key are host configuration and may intentionally target a
   private or HTTP service, but repository content must never select them. The
   current public CLI does not construct this adapter, so the documented
   trusted-host assumption is acceptable. Hosts should reject plaintext HTTP
   when a credential is present unless explicitly configured for a local
   endpoint.
3. Yes for credentials currently sent. `Authorization` is the only sensitive
   request header added by these adapters. Any future credential-bearing
   header must be added to the redirect policy and tests.
4. Yes. 16 MiB is larger than a normal model reply but provides a clear memory
   bound. Hosts needing a tighter operational limit should make it
   configurable downward in a later change.
5. Mostly. The trusted-caller assumption is present, but host integrations
   must not pass untrusted user paths through unchanged. This is acceptable
   only as an embedding contract, not as validation supplied by Core.
6. Acceptable for the declared read-only local use case because it affects
   what is read, not write authority, and later verification detects content
   drift. It is not acceptable as a general filesystem sandbox.
7. Sufficient for the observed-repository commands currently used. The
   `atlas propose` textconv and `reference-transaction` hook exposure is
   acceptable only because the target repository and test command are already
   trusted caller-controlled execution surfaces. Centralising hardened Git
   invocation and explicitly disabling textconv would reduce regression risk.
8. No. It proves consent by the terminal controller, but not permission
   external to an autonomous agent. It therefore does not satisfy the current
   unqualified exit wording.

## Known residual risks and open conditions

| Item | Decision | Reason |
| --- | --- | --- |
| R1 | Acceptable | Capability and evidence gates, not model obedience, are the security boundary. |
| R2 | Acceptable | Clearly documented trusted-host boundary; Core is not an OS sandbox. |
| R3 | Acceptable | Bounded public CLI exists; unsafe/in-process alternatives are explicit host choices. |
| R4 | Acceptable | Windows bounded execution fails closed. Lack of support is preferable to a soft limit. |
| R5 | Acceptable | Narrow read-only TOCTOU window, final-component protection and later integrity verification are documented. |
| R6 | Acceptable | Redaction is correctly described as shape-based, not comprehensive. Hosts remain responsible for source selection. |
| R7 | Needs process control | Baseline changes require human inspection; the canary does not prove every baseline entry is safe. Non-blocking for code closure. |
| R8 | Acceptable | The caller explicitly supplies a command in its own trusted repository. It must remain documented as unsandboxed. |
| R9 | Acceptable | The concrete proposal use case binds and atomically verifies the base ref. Future write cases need the same property. |
| R10 | Acceptable | CAS rollback avoids deleting another actor's ref; irreversible test/hook side effects are correctly disclosed. |
| R11 | **Blocking** | Same issue as IR-1/F4. |
| R12 | Acceptable with follow-up | Observed-repository execution is fixed. Remaining commands operate in the caller-trusted proposal repository, but hardening should be centralised. |
| H1 | Needs improvement | Zero required approvals weakens governance and permits self-merge. Not by itself a product-code blocker, but require one approval before calling the hosting process production-grade. |
| H2 | Needs improvement | Weekly version PRs and audit exist, but security updates should be enabled. Non-blocking while strict audit remains required. |
| H3 | Acceptable | Fixed and covered by the workflow command now used. |
| C1 | **Blocking** | Required release artifacts and retained digests are not attached to a release tag. |
| C2 | Acceptable for this baseline | PR #93 records maintainer review and exact-head CI. Formal required approval remains absent under H1. |
| C3 | Acceptable | Re-checked: strict required `python` status is active on `main`. |
| C4 | Acceptable | The workflow runs on pull requests and main and retains the canary step. |
| C5 | Completed by this report | Independent review performed, with the blockers above. |

## Accepted residual risks

R1–R6 and R8–R10 are accepted for the stated v2.0 product boundary. The
project owner should retain the current documentation and review them at each
minor release. R7, R12, H1 and H2 need tracked owner actions by the next minor
release. R11/F4 and C1 are not accepted and must not be relabelled residual
risk by the implementer of those controls.

## Conclusion

- Blocking findings remaining at the reviewed commit: **YES** — IR-1/F4/R11
  and C1. The branch contains an unreviewed remediation for IR-1/F4/R11.
- Conclusion: **Not suitable for Atlas Core v2.0 security-gate closure.**
- Conditions: implement and independently re-review an approval boundary that
  an autonomous proposer cannot satisfy itself; publish and retain the exact
  verified release bundle at the release tag. Then update the report against
  that exact commit and re-check current hosting controls.

OpenAI Codex — 2026-09-27
