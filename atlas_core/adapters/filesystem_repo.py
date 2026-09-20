from __future__ import annotations

from pathlib import Path

from ..budget import RunBudget

CANDIDATE_FILES = [
    "README.md", "pyproject.toml", "package.json", "docs/architecture.md",
    "docs/CONTEXT_CONTRACT.md", "docs/TOKEN_BUDGET.md",
    "docs/context-export-contract.md", "docs/memory-model.md",
    "docs/roadmap-token-reduction.md", ".github/workflows/test.yml",
    ".github/workflows/run-atlas.yml",
]


class FilesystemRepoAdapter:
    """Read a small, fixed local surface; optional shared budget for bounded runs."""

    def __init__(self, repo_path: str, max_chars_per_file: int = 1200):
        self.repo_path = Path(repo_path).expanduser().resolve()
        if not isinstance(max_chars_per_file, int) or max_chars_per_file < 1:
            raise ValueError("max_chars_per_file must be positive")
        self.max_chars_per_file = max_chars_per_file

    def observe(self, task: str, *, budget: RunBudget | None = None) -> list[str]:
        observations: list[str] = []
        if budget is not None:
            budget.check()
        if not self.repo_path.exists():
            return [f"Repo path not found: {self.repo_path}"]
        observations.append(f"Local repo path: {self.repo_path}")

        for rel in CANDIDATE_FILES:
            if budget is not None:
                budget.check()
            path = self.repo_path / rel
            # Do not follow a symlink outside the chosen root. A caller-provided
            # repository may contain hostile symlinks.
            if not path.resolve().is_relative_to(self.repo_path):
                continue
            if not path.exists() or not path.is_file():
                continue
            if budget is not None:
                budget.reserve_tool()
            try:
                if budget is None:
                    text = path.read_text(encoding="utf-8", errors="replace")
                else:
                    # Never read the whole file just to display a short excerpt.
                    with path.open("r", encoding="utf-8", errors="replace") as stream:
                        text = stream.read(self.max_chars_per_file + 1)
                    budget.check()
            except OSError as exc:
                if budget is not None:
                    raise OSError(f"repository read failed: {rel}") from exc
                observations.append(f"{rel}: could not read ({exc})")
                continue
            observations.append(_summarize_file(rel, text, self.max_chars_per_file))

        if len(observations) == 1:
            observations.append("No standard repo surfaces found. Try running from repo root or pass --repo-path explicitly.")
        return observations


def _summarize_file(rel: str, text: str, limit: int) -> str:
    lines = text.splitlines()
    head = "\n".join(lines[:80])
    if len(head) > limit:
        head = head[:limit].rstrip() + "..."
    return f"{rel}:\n{head}"
