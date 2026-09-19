from __future__ import annotations

from pathlib import Path

from .router import list_routes


SKILL_NAME = "atlas-core-loop"


def generate_chatgpt_skill(output_dir: str | Path, *, force: bool = False) -> Path:
    """Generate a thin Skill wrapper that delegates execution to Atlas Core."""
    package_dir = Path(output_dir) / SKILL_NAME
    if package_dir.exists() and not force:
        raise FileExistsError(f"skill package already exists: {package_dir}")

    references_dir = package_dir / "references"
    references_dir.mkdir(parents=True, exist_ok=True)
    (package_dir / "SKILL.md").write_text(_render_skill(), encoding="utf-8")
    (references_dir / "routes.md").write_text(_render_routes(), encoding="utf-8")
    return package_dir


def _render_skill() -> str:
    return """---
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
"""


def _render_routes() -> str:
    lines = [
        "# Atlas Core Routes",
        "",
        "Generated from `atlas_core.router.ROUTES`. Regenerate this package after route changes.",
        "",
        "| Route | Risk | Steps |",
        "| --- | --- | --- |",
    ]
    for name, spec in list_routes().items():
        steps = " -> ".join(spec["steps"])
        lines.append(f"| `{name}` | {spec['risk_level']} | {steps} |")
    lines.extend(
        [
            "",
            "Inspect the live route map with:",
            "",
            "```bash",
            "atlas routes",
            "```",
        ]
    )
    return "\n".join(lines) + "\n"
