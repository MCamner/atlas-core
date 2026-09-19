---
name: atlas-core-loop
description: Run bounded Atlas Core analysis for repo reviews, architecture decisions, root-cause analysis, comparisons, learning, or prompt improvement.
---

# Atlas Core Loop

Use the installed `atlas` command as the execution authority. Do not imitate the
loop from this document when the command is available.

## Workflow

1. Run `atlas run "<task>"`.
2. Add `--repo-path <path>` or `--repo <owner/name>` when current repository
   evidence is needed.
3. Read [references/routes.md](references/routes.md) only when route selection or
   route-specific behavior needs inspection.
4. Return the executed result, including its recommendation, next step, and
   confidence. Execute the selected route; do not merely name it.

For structured state, run:

```bash
atlas run "<task>" --json
```

## Safety boundary

Atlas Core is read-only except for explicitly configured memory-candidate
output. Obtain explicit approval immediately before file changes, commits,
pushes, pull requests, issues, merges, deletes, or other external mutations.
Treat mqobsidian context as durable memory, not current runtime truth; verify
runtime-sensitive claims against the source repository or service.
