# Operations Runbook

Atlas Core is a library/CLI, not a hosted service. The operator owns provider
availability, local files, event-log retention and OS isolation. Use a new run
for a new attempt; do not edit a prior run document to make it appear healthy.

## Provider unavailable or rate-limited

1. Stop retrying if the run ended `tool_error`; Core does not silently fall
   back to deterministic output after a configured provider fails.
2. Inspect `metadata.failure` for the provider stage and error type. Check
   endpoint health, credentials, timeout and provider rate limits without
   copying the secret into logs or a ticket.
3. Retry only after the provider condition is understood. Use a fresh run id
   and an explicit budget; provider replies are non-deterministic.
4. If no provider is configured, deterministic execution is a different mode,
   not a recovery result equivalent to the failed model run.

## Memory unavailable

1. Treat the failed memory operation as unavailable context, not as evidence
   about current repository state. Durable memory is not runtime truth.
2. Preserve the original error and avoid repeatedly writing the same
   candidate. Do not hand-edit an append-only memory record to repair it.
3. Continue without memory only when the task can be answered from freshly
   observed sources and the operator explicitly starts that run without the
   memory adapter. Otherwise stop and restore the memory adapter/store first.

## Partial or stale observations

1. Check each observation's path, line range, digest and `read_in_full` state.
   A partial excerpt can establish literal presence, but not absence from the
   entire file.
2. Do not summarize `source_lacks_literal` over an incomplete excerpt as a
   source-wide absence. Ask the host to read the remaining range or stop.
3. If drift is reported, treat the run as `blocked`; capture a new snapshot and
   rerun. Do not combine observations from different snapshots.

## Approval timeout or refusal

1. An approval is single-use, bound to an exact operation and expires within
   one hour. Expired, reused, changed-diff or moved-base approvals are refused
   before the write handler runs.
2. Re-read the proposed diff and current base. If anything changed, discard
   the old proposal and generate a new one; never renew approval by reusing its
   token.
3. `atlas propose` creates only an `atlas/*` branch and does not push or merge.
   Inspect its post-action checks and rollback result before proceeding.

## Resume failure

1. Preserve the event log and inspect it with `atlas inspect RUN_ID
   --event-log PATH`. An unfinished call is `unknown`, not evidence that it
   failed before producing side effects.
2. Resume only when Core accepts the original task, snapshot, evidence digests
   and iteration bound. A non-idempotent unfinished call or `ResumeRefused`
   requires operator investigation; do not edit the log or replay it manually.
3. If recovery cannot be proven safe, start a new run with a new id and fresh
   observations. Retain the interrupted log for audit.

## Incorrect release

1. Stop publishing/downloading the affected artifact and record its version,
   tag and digest. Do not move a published tag.
2. Determine whether the problem is a package, schema, security or support
   claim. Follow the API migration policy for wire-contract changes.
3. Publish a corrected higher patch version after the release checklist passes.
   Tell consumers which version is affected and whether they must migrate data.
4. Preserve the failed artifact and incident evidence; do not silently replace
   it. Re-run the installed-wheel smoke test before reopening distribution.

See [the API contract](api-contract.md), [safety model](safety-model.md) and
[release checklist](release-checklist.md) for the exact contracts and gates.
