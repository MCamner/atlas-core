from __future__ import annotations

from pathlib import Path

CANDIDATE_FILES = [
    "README.md",
    "pyproject.toml",
    "package.json",
    "docs/architecture.md",
    "docs/CONTEXT_CONTRACT.md",
    "docs/TOKEN_BUDGET.md",
    "docs/context-export-contract.md",
    "docs/memory-model.md",
    "docs/roadmap-token-reduction.md",
    ".github/workflows/test.yml",
    ".github/workflows/run-atlas.yml",
]


class FilesystemRepoAdapter:
    """Read small, useful surfaces from a local repository path."""

    def __init__(self, repo_path: str, max_chars_per_file: int = 1200):
        self.repo_path = Path(repo_path).expanduser().resolve()
        self.max_chars_per_file = max_chars_per_file

    def observe(self, task: str) -> list[str]:
        observations: list[str] = []

        if not self.repo_path.exists():
            return [f"Repo path not found: {self.repo_path}"]

        observations.append(f"Local repo path: {self.repo_path}")

        for rel in CANDIDATE_FILES:
            path = self.repo_path / rel
            if not path.exists() or not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except Exception as exc:  # pragma: no cover - defensive
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
