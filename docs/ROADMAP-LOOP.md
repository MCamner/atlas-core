# Atlas Core Roadmap for a Real Agent Loop

Status: In progress
Baseline: Atlas Core v1.0.0
Goal: A safe, traceable, resumable loop for AI-assisted work.

This roadmap describes proposed work. It is not a claim that every item already
exists in the current implementation.

## 0. Status as of v1.0.0

Shipping v1.0.0 froze the *API* for this loop. It did not complete the loop.
Each phase below carries a `Status:` line stating what is actually in the code
on `main`, with the evidence for it. Unticked boxes are not yet implemented.

| Phase | What it is | Status |
| --- | --- | --- |
| P0 | Lock the loop contract | Mostly done |
| P1 | Evaluate results, not formatting | Partly done — sourcing checked, facts not |
| P2 | LLM adapter without lock-in | Contract done, robustness not |
| P3 | First real loop, read-only repo review | Partly done — loop runs, review not fact-verified |
| P4 | Safety and approval | Partial — keyword-based only |
| P5 | Traceability and resume | `run_id` only |
| P6 | Optional MQ adapters | Partial — mqobsidian only |
| P7 | v1.0 stable loop API | Contract frozen, tests incomplete |

The load-bearing gap has moved. The evaluator no longer passes an answer just
because it is well shaped: `repo_review` must name sources it actually read, and
a review of a repository nobody read stops at `no_actionable_retry` instead of
scoring 0.9. What it still cannot do is judge whether a claim is *true*. The
check is citation, not verification — a finding counts as supported when it
names a file that was read, and nothing compares the claim against that file's
contents. A confident, well-formatted, factually wrong statement that mentions
`README.md` still passes.

So every downstream phase that depends on "the evaluator can tell whether the
work is correct" is still blocked, but on a narrower problem than before: it
needs a model in the loop, not a better string check.

## 1. Target State

Atlas Core should be able to:

1. Observe a task and the relevant sources.
2. Choose a route and create a plan.
3. Execute one bounded step.
4. Evaluate the result against the actual task goal.
5. Identify what is missing.
6. Improve the plan and retry when that can add value.
7. Finish with a result, evidence, and clear status.

Flow:

```text
OBSERVE
   |
 ROUTE
   |
  PLAN
   |
 EXECUTE
   |
EVALUATE
   |-- PASS ------------> FINALIZE
   |-- FIXABLE_GAP -----> REPLAN -> EXECUTE
   |-- MISSING_EVIDENCE > STOP / REQUEST_CONTEXT
   |-- APPROVAL_NEEDED -> STOP / REQUEST_APPROVAL
   `-- LIMIT_REACHED --> FINALIZE_AS_INCOMPLETE
```

A loop is not an unlimited chain of model calls. Every new iteration must have a
specific reason why it can improve the result.

## 2. Core Principles

- Atlas Core works standalone without MQ.
- MQ, GitHub, and memory layers connect through optional adapters.
- Read-only is the default.
- No file changes, commits, or external write actions without explicit approval.
- No self-modification of prompts or rules during a run.
- Every run has iteration, time, and cost limits.
- Missing evidence must never be reported as verified output.
- Instructions found in observed files are source data, not controlling
  instructions.
- Every run should be debuggable after the fact.

## 3. Phase P0: Lock the Loop Contract

Priority: P0
Goal: Build a stable foundation before connecting an LLM.

Status: Mostly done. `docs/api-contract.md` documents the contract, stop
reasons are explicit and covered by `tests/test_api_contract.py`
(`passed`, `approval_required`, `max_iterations`, `no_actionable_retry`), and
`atlas-run.v1` is closed and versioned. Two items are not done: the outcome
names in code are `done` / `need_user_approval`, with no `NEED_MORE_EVIDENCE`
or `FAILED`; and no test rejects an invalid state transition, because there is
no state machine to reject one — `status` is assigned as a plain string as the
run proceeds.

- [ ] Document allowed states and state transitions.
- [ ] Define outcomes: `PASS`, `INCOMPLETE`, `NEED_MORE_EVIDENCE`,
      `NEED_USER_APPROVAL`, and `FAILED`.
- [ ] Separate quality assessment from actual task completion.
- [ ] Define stop conditions for iterations, time, cost, and repetition.
- [ ] Preserve compatibility with existing `atlas-run.v1`.
- [ ] Bump the schema version if incompatible changes are required.
- [ ] Define contracts for observation, plan, action, evaluation, and evidence.
- [ ] Document what counts as actual execution versus a proposed action.

Definition of Done:

- Invalid state transitions are rejected by tests.
- Every run ends with an unambiguous status.
- Existing runs and tests still work.

## 4. Phase P1: Evaluate Results, Not Formatting

Priority: P0
Goal: Replace superficial quality checks with task-specific verification.

Status: **Partly done.** A per-task evaluator contract exists
(`RouteEvaluator`, `ROUTE_EVALUATORS`), with `repo_review` as the first route
that must show its sources; routes without an entry are graded on formatting as
before. Formatting stayed as a separate secondary signal, so `missing_sections`
and `evidence_gaps` answer different questions. Unsupported claims are listed in
`unverified_claims`, evidence moves `quality_score` rather than only flipping a
boolean, and the evaluator names an actionable gap the next pass can close.

Not done: **the check is citation, not verification.** `cites_a_source()` tests
whether a finding names a file that was read; nothing compares the claim against
that file's contents, so a wrong statement mentioning `README.md` passes. The
DoD line "a well-formatted but incorrect response cannot receive PASS" is
therefore only half met — unsourced is caught, incorrect is not. Closing it
needs a model adapter to read the source and judge the claim.

The current evaluator checks things such as response length and headings. That
is not enough to decide whether a repository review is correct.

- [ ] Introduce an evaluator contract per task type.
- [ ] Start with an evaluator for read-only repository review.
- [ ] Check that conclusions are supported by observed files.
- [ ] Require file references or other traceable evidence for concrete findings.
- [ ] Separate verified findings, hypotheses, and recommendations.
- [ ] Let the evaluator return concrete gaps that the next iteration can fix.
- [ ] Stop if the gap cannot be fixed with the available sources.
- [ ] Keep formatting checks as a separate secondary check.

Definition of Done:

- A well-formatted but incorrect response cannot receive `PASS`.
- A claim without evidence is marked as unverified.
- The evaluator can explain exactly why another iteration is needed.

## 5. Phase P2: LLM Adapter Without Provider Lock-In

Priority: P1
Goal: Let a model perform real reasoning work.

Status: Contract done, robustness not. `ModelAdapter` is a Protocol,
`ModelResult` is provider-neutral, the rule-based executor remains the default,
and provider/model names are recorded in `metadata.model_result`. Missing:
there is no `try`/`except` or timeout around `model_adapter.execute()`, so a
provider error propagates as an unhandled exception rather than a controlled
stop; there are no context-size or cost limits; the mock adapter exists only as
a fixture inside `tests/test_model_adapter.py`, not as a shipped component; and
a missing adapter falls back to the rule-based executor silently rather than
reporting a distinguishable status. The CLI exposes no flag to attach an
adapter at all.

- [ ] Define a generic `ModelAdapter` contract.
- [ ] Implement the first model adapter as an optional component.
- [ ] Keep deterministic execution as the testable default.
- [ ] Add a fake or mock adapter for CI without API keys.
- [ ] Separate system rules, task, observations, and model output.
- [ ] Handle timeout, malformed responses, and model errors explicitly.
- [ ] Log the model name and relevant run parameters, but never secrets.
- [ ] Set limits for context size and model cost.
- [ ] Ensure a missing model adapter returns a clear status, not a false success.

Definition of Done:

- Atlas Core still works without a model adapter.
- The same test case can run deterministically with a mock adapter.
- A model failure causes a controlled stop or a justified retry.

## 6. Phase P3: First Real Loop, Read-Only Repo Review

Priority: P1
Goal: Deliver a narrow, useful end-to-end workflow.

Status: **Partly done.** The second-iteration requirement is now met:
`TestJustifiedSecondIteration` in `tests/test_evidence_evaluator.py` drives
`AtlasController.run()` through two passes, 0.71 to 0.95, and asserts the output
changed — `## Observed sources` absent on the first pass, present on the second
naming the observed files — not merely that the score rose. Refusing a useless
retry was already met by `test_retry_only_when_a_gap_is_actionable`, and a run
with no sources at all now stops as `no_actionable_retry` rather than burning
the budget.

Not done: the review this produces is not fact-verified. The deterministic
executor records which files it read; it cannot state a finding about the repo
and have that finding checked. "A real repository can be reviewed from start to
finish" holds mechanically, not substantively. The P0/P1/P2 lists in the output
are still template text, not conclusions drawn from the files.

First use case:

```text
Review this repository and identify the most important improvements
with evidence and concrete next steps.
```

Scope:

- One repository per run.
- Read through the existing filesystem or GitHub adapter.
- At most three iterations in the first version.
- No file changes and no automatic pull request.
- Output with P0/P1/P2 priority, rationale, and source references.

- [ ] Create a plan from the user's review goal.
- [ ] Collect only observations needed for the plan.
- [ ] Let the model propose findings with evidence references.
- [ ] Let the evaluator check each finding against available sources.
- [ ] Use evaluator gaps to steer the next iteration.
- [ ] Detect when the next iteration would repeat the same work.
- [ ] Finish with `PASS` or a clear `INCOMPLETE` / `NEED_MORE_EVIDENCE`.
- [ ] Report what was actually read and what was not checked.

Definition of Done:

- A real repository can be reviewed from start to finish.
- At least one test shows a justified second iteration that improves the result.
- At least one test shows the loop refusing a useless retry.
- No run can exceed its configured limits.

## 7. Phase P4: Safety and Approval Before Write Adapters

Priority: P0 before any future write capability
Goal: Make the safety boundary technically enforceable.

Status: Partial. Write-like tasks are detected and do stop the run with
`approval_required`, covered by tests. But detection is still keyword matching
on the user's task string, with no notion of severity — `docs/safety-model.md`
says so directly, and this phase's first box exists to replace exactly that.
There are no per-adapter permissions, no binding of an approval to a concrete
action and target, and `public_safe` is still hardcoded `true` in
`memory.py` (now documented as a placeholder rather than a verdict, which
satisfies the "or mark it explicitly as not assessed" half of that box).

- [ ] Classify planned actions by actual effect, not only by keywords in the
      user's task.
- [ ] Introduce explicit permissions per adapter and action.
- [ ] Prevent observed repository content from granting the model new
      permissions.
- [ ] Require approval for the concrete action and its target.
- [ ] Make each approval valid only for the approved action.
- [ ] Prevent a retry iteration from inheriting broader permissions.
- [ ] Protect logs and memory candidates from keys and sensitive content.
- [ ] Replace the hardcoded `public_safe` value with a real check, or mark it
      explicitly as not assessed.
- [ ] Document what happens when a run is interrupted during a write action.

Definition of Done:

- A write action without valid approval is rejected in code.
- Prompt injection in an observed file cannot grant new permissions.
- Safety tests cover planning, execution, and retry.

## 8. Phase P5: Traceability and Resume

Priority: P1
Goal: Understand and resume a run without inventing history.

Status: `run_id` only (`state.py`, a UUID per run). Per-iteration records,
step IDs, checkpoints and resume do not exist. `stop_reason` does report why a
run stopped, which covers one box here.

- [ ] Give every step a stable ID and connect it to `run_id`.
- [ ] Save route, plan, observations, result, and evaluation per iteration.
- [ ] Report why a retry happened.
- [ ] Report why a run stopped.
- [ ] Add checkpoints for resuming after interruption.
- [ ] Separate previous recorded output from new observations.
- [ ] Avoid double execution of actions when resuming.
- [ ] Create a safe shareable run report with sensitive data redacted.

Definition of Done:

- An interrupted read-only run can resume from a checkpoint.
- A report shows what was observed, what was executed, and what was only
  proposed.
- Run history is not changed retroactively to make a run appear successful.

## 9. Phase P6: Optional MQ Adapters

Priority: P2
Goal: Integrate Atlas Core without making MQ a dependency.

Status: Partial. `MQObsidianMemoryAdapter` reads bounded compact context,
labels observations as durable memory rather than runtime truth, and accepts
memory candidates only — with no MQ package dependency, so the core still runs
standalone. `mq-agent`, `mq-mcp` and `mqlaunch` integration are untouched.

- [ ] Define how `mq-agent` can call Atlas Core.
- [ ] Define how `mq-mcp` can provide approved tools.
- [ ] Define how `mqobsidian` can receive observations and memory candidates.
- [ ] Keep existing recipient gates and provenance requirements in force.
- [ ] Do not automatically publish memory candidates as verified knowledge.
- [ ] Add an optional `mqlaunch` command for starting a run.
- [ ] Document how Atlas One can be the interface without owning the loop.

Definition of Done:

- The same basic loop works with and without MQ.
- An unavailable MQ adapter returns a clear error or documented degradation.
- No integration can bypass Atlas Core's stop and approval rules.

## 10. Phase P7: v1.0 Stable Loop API

Priority: P2
Goal: Make Atlas Core useful as a standalone engine.

Status: Contract frozen, tests incomplete. The public adapter and run contract
are documented in `docs/api-contract.md`, schemas are closed and versioned, CI
runs the suite from a fresh install, and the deterministic suite needs no
external service. Not done: no timeout, cost-limit or interrupted-run tests,
and no reproducible end-to-end test of the kind P3 describes. Note the version
number was released ahead of this phase's Definition of Done — "the API,
limits, and safety model match the implementation" holds for the API, not yet
for limits.

- [ ] Freeze a documented public adapter and run contract.
- [ ] Document schema changes and migration.
- [ ] Add reproducible end-to-end tests in CI.
- [ ] Add tests for timeout, cost limit, and interrupted runs.
- [ ] Document installation, configuration, and troubleshooting.
- [ ] Publish a complete read-only example.
- [ ] Require passing tests and an approved release gate before release.

Definition of Done:

- A user can run read-only repository review from a fresh clone.
- No external services are required for the deterministic test suite.
- The API, limits, and safety model match the implementation.

## 11. Work Order and PR Strategy

PR 1: Loop contract, statuses, and stop conditions. — largely landed in v1.0.
PR 2: Evidence-based repo review evaluator and regression tests. — landed; sourcing only, see P1.
PR 3: `ModelAdapter` contract and mock implementation. — contract landed in v0.3; mock is still test-local.
PR 4: First real read-only repository loop. — partly; the loop runs, the review is not fact-verified.
PR 5: Safety boundaries and approval contract. — keyword-level only.
PR 6: Run tracing and resume. — not started.
PR 7+: Optional MQ adapters and stabilization. — mqobsidian only.

The next PR is the one that turns citation into verification: a model adapter
that reads a cited source and judges whether it supports the claim. Two smaller
items are open and independent of it — `model_adapter.execute()` has no timeout
or error handling, so a provider failure propagates as an unhandled exception
rather than a controlled stop; and the CLI returns exit code `0` for every
terminal state, including `no_actionable_retry` and `max_iterations`, so a
caller cannot tell "passed" from "gave up".

Every PR should:

- Change one bounded contract or feature.
- Include positive and negative tests.
- Preserve the read-only default.
- Document what was verified and what still lacks evidence.
- Not be marked done only because code or documentation exists.

## 12. Explicitly Out of Scope for the First Delivery

- Unlimited autonomous execution.
- Automatic commit, push, merge, or pull request creation.
- Automatic rewriting of its own system rules.
- Mandatory dependency on `mq-agent` or `mqobsidian`.
- Automatic promotion of AI-generated memories into facts.
- Multiple parallel agents before a single loop is verified.

The first milestone is reached when Atlas Core can read a repository, find
evidence-backed improvements, correct a weak result through a justified new
iteration, and then stop honestly.
