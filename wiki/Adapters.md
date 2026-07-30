# Adapters

Adapters let Atlas Core talk to external systems without making those systems part of the core.

## Core rule

```text
Atlas Core must not know what MQ is.
```

The core should only know abstract capabilities:

- observe context
- read repository state
- read memory candidates
- execute a model call
- write a memory candidate
- report a result

## Adapter examples

### Local filesystem repo adapter

Reads a local checkout.

Use when:

```bash
atlas run "granska atlas-core" --repo-path .
```

### GitHub repo adapter

Reads a public GitHub repo.

Use when:

```bash
atlas run "granska MCamner/mqobsidian" --repo MCamner/mqobsidian
```

### Local memory adapter

Writes optional memory candidates.

Use when:

```bash
atlas run "förbättra min prompt" --memory-dir .atlas-memory
```

### Future LLM adapter

Should provide live model output while keeping the core deterministic and testable.

Expected shape:

```text
input: task + route + context + plan
output: result + reasoning summary + confidence + caveats
```

### Future mqobsidian adapter

Should read durable memory and context packs from mqobsidian, but mqobsidian must not become the source of truth for runtime code.

Use mqobsidian for:

- memory
- context packs
- durable project notes
- prior decisions

Do not use mqobsidian as the only source for:

- current code behavior
- CI state
- latest file content
- active PR changes

## Write boundary

Write actions require explicit approval.

Adapters should default to read-only behavior unless the user clearly requests a write operation.

## Design principle

```text
Adapters can change. The loop contract should stay stable.
```
