---
name: Bug report
about: Something in the loop, a route, or an adapter behaves incorrectly
title: ""
labels: bug
---

## What happened

## What you expected

## Reproduction

The task string and flags you ran:

```bash
atlas run "<task>" --repo-path .
```

## Output

Paste the relevant part of the run output. Include the trailer if you have it:

```text
Atlas route: <route>
Iterations: <n>/<max>
Quality score: <score>
Status: <status>
```

## Environment

- Atlas Core version (`atlas version`):
- Python version (`python3 --version`):
- OS:

## Notes

Atlas Core is read-only by default. If you hit something that looks like it
tried to write, say so explicitly — that is a priority bug.
