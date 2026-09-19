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

The first job was to make the loop testable and stable.

A live model provider attaches as an adapter (`ModelAdapter`) so the core does not depend on one vendor, one API, or one local setup. No provider binding is shipped in the box; the rule-based executor is the default.

## Can Atlas Core read GitHub repos?

Yes. Atlas Core reads public GitHub repo observations through the `--repo` option.

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

## What is already shipped in 1.0?

The full v0.1–v1.0 roadmap:

```text
core loop, repo observations, model adapter contract,
mqobsidian adapter, ChatGPT Skill generator, stable loop API
```

See [[Roadmap]] for what each version added.

## What should be built next?

Nothing is required for the loop contract itself; 1.x is a compatibility promise, not a feature backlog. The open work is concrete adapters on top of it — a shipped provider binding for `ModelAdapter`, and severity-aware write approval instead of the current keyword check.
