# Atlas Core Wiki

Atlas Core is a standalone loop engine for routed, evaluated, retryable AI-assisted work.

It turns Atlas from a prompt/router system into a small runtime loop:

```text
observe → route → plan → execute → evaluate → retry/replan → finalize
```

Atlas Core is intentionally independent from the MQ stack. MQ, GitHub, Obsidian, ChatGPT Skills, and local memory should plug in as adapters — not become the core.

## Quick links

- [[Getting Started]] — install and run Atlas Core locally
- [[Core Loop]] — how the loop works
- [[Routes]] — how tasks are classified
- [[Adapters]] — how GitHub, local files, memory, and future MQ integrations attach
- [[GitHub Actions]] — how to run Atlas from Actions
- [[Roadmap]] — planned versions and boundaries
- [[FAQ]] — common questions and design decisions

## Current status

v0.2.0 is a working scaffold:

- deterministic route selection
- route map
- task planner
- rule-based executor
- evaluator
- bounded max-iteration loop
- local memory candidate adapter
- local filesystem repo observations
- public GitHub repo observations
- JSON schemas
- tests
- GitHub Actions runner
- optional ChatGPT Skill wrapper

Atlas Core does **not** include a live LLM provider by default. That belongs in a future adapter.

## Design rule

```text
Core stays small.
Adapters carry environment-specific behavior.
Writes require explicit approval.
Evaluation decides when to stop.
```
