# Migrating Atlas 1.x Prompt Flows

There is no automatic importer for Atlas One data: this repository does not
define or validate an Atlas One export format. Migration is opt-in and
copy-based. Existing prompts are never executed, overwritten or deleted by
Atlas Core.

[`examples/atlas-one-migration-smoke.md`](../examples/atlas-one-migration-smoke.md)
records one fixture-based preview. Its test verifies the archive hash is
unchanged, preserves an unmapped write instruction, and emits an explicit task
without invoking Atlas or granting write capability. This demonstrates the
manual handoff, not compatibility with an external Atlas One export format.

## Safe migration procedure

1. Export or copy the existing prompt collection to a read-only archive. Keep
   original bytes, filenames, ordering, metadata and referenced files. Record
   a file count and SHA-256 manifest before conversion.
2. Select one prompt explicitly. Do not batch-run prompts or infer that a
   prompt's presence grants tool, network or write permission.
3. On a separate copy, classify its content as task wording, policy/method,
   route intent, context reference or action. Move reusable method guidance
   into a reviewed adapter/host prompt; express the specific requested work as
   an explicit `atlas run` task. Keep unresolved material in the archive and
   note it as unmapped rather than discarding it.
4. Map repository reads to an explicit snapshot/observer. Map integrations to
   host-supplied adapters with declared read-only capabilities. A legacy
   instruction to write is not approval; use a separately reviewed
   `atlas propose` diff and an explicit human approval.
5. Review the converted task and all observations before starting the run.
   The operator must invoke `atlas run` deliberately for that one task. Without
   a configured provider the deterministic executor is used; provider errors
   fail closed.
6. Compare the source archive with the conversion manifest. Require the same
   source count and hashes, and a human decision for every unmapped item.
   Keep the archive until the owner accepts the migration.

## Mapping and limits

| Atlas 1.x material | Atlas Core destination | Default during migration |
| --- | --- | --- |
| Reusable instructions | Host/adapter method prompt, reviewed separately | Preserve; do not auto-load as executable policy |
| One-off request | Explicit `atlas run` task | Do not execute automatically |
| Repository or memory references | Explicit observer/adapter configuration | Do not infer filesystem paths or trust old snapshots |
| Tool or write instruction | Reviewed tool contract; write via approval-gated proposal | Disable until a person reviews the capability |
| Unknown fields or attachments | Unmapped migration manifest plus original archive | Preserve byte-for-byte |

The `migrate_run()` function is only for versioned `atlas-run` documents; it is
not an Atlas One prompt importer. Do not treat it as one. A future importer
needs a published source format, lossless mapping tests and an opt-in preview
before it can replace this manual path.
