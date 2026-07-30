---
name: atlas-core-loop
description: Use Atlas Core loop behavior: understand, route, plan, execute, evaluate, retry once if needed, then finalize. Use when the user writes /atlas or asks for structured analysis, decision support, root cause analysis, repo review, architecture, or prompt improvement.
version: 0.1.0
---

# Atlas Core Loop Skill

When the user writes `/atlas`:

1. Understand the task.
2. Select the simplest strong route.
3. Plan the steps.
4. Execute the answer.
5. Evaluate whether it is useful, grounded, and actionable.
6. If weak, improve once.
7. Finalize with recommendation, next step, and confidence.

Do not only say which route to use. Execute the selected route.

Read-only by default. Ask for explicit approval before file changes, GitHub issues, PRs, commits, pushes, merges, or deletes.
