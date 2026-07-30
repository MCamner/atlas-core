# FAQ

## Is Atlas Core the same as Atlas Router?

No.

Atlas Router selects a method or prompt route.

Atlas Core runs a bounded loop:

```text
observe → route → plan → execute → evaluate → final
```

Routing is one stage inside the loop.

## Is Atlas Core part of MQ?

No.

Atlas Core is intentionally independent. MQ can connect later through an adapter.

## Why is there no live LLM provider by default?

The first job is to make the loop testable and stable.

A live model provider should be added as an adapter so the core does not depend on one vendor, one API, or one local setup.

## Can Atlas Core read GitHub repos?

Yes, v0.2.0 can read public GitHub repo observations through the `--repo` option.

Example:

```bash
atlas run "granska MCamner/mqobsidian" --repo MCamner/mqobsidian
```

## Can Atlas Core read local repos?

Yes.

```bash
atlas run "granska atlas-core" --repo-path .
```

## Can Atlas Core write files or create PRs?

Not by default.

The design principle is read-only first. Write actions require explicit approval and should be routed through adapters with clear safety boundaries.

## What is the difference between memory and source truth?

Memory is useful context.

Source truth is current reality.

For code behavior, CI status, and current file content, use the live repository and workflow state. Use memory for prior decisions, notes, and context packs.

## What should be built next?

The most useful next step is v0.3:

```text
LLM adapter contract + provider-neutral model result schema
```

That gives Atlas Core real execution power without making the core provider-specific.
