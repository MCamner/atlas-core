from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request

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


class GitHubRepoAdapter:
    """Small GitHub reader adapter using the public GitHub REST API.

    It works for public repositories without auth. Set GITHUB_TOKEN for private repos
    or higher rate limits. It intentionally reads a small known surface first.
    """

    def __init__(self, repo_full_name: str, ref: str | None = None, max_chars_per_file: int = 1200):
        if "/" not in repo_full_name:
            raise ValueError("repo_full_name must be in owner/name form")
        self.repo_full_name = repo_full_name
        self.ref = ref
        self.max_chars_per_file = max_chars_per_file
        self.token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")

    def observe(self, task: str) -> list[str]:
        observations: list[str] = [f"GitHub repo: {self.repo_full_name}"]

        meta = self._get_json(f"https://api.github.com/repos/{self.repo_full_name}")
        if meta:
            default_branch = meta.get("default_branch") or "main"
            observations.append(
                "Repo metadata: "
                f"description={meta.get('description')!r}, "
                f"default_branch={default_branch}, "
                f"visibility={meta.get('visibility')}, "
                f"archived={meta.get('archived')}"
            )
        else:
            default_branch = "main"
            observations.append("Repo metadata could not be fetched. Continuing with default branch assumption: main.")

        ref = self.ref or default_branch
        found = 0
        for rel in CANDIDATE_FILES:
            text = self._fetch_file(rel, ref)
            if text is None:
                continue
            found += 1
            observations.append(_summarize_file(rel, text, self.max_chars_per_file))

        if found == 0:
            observations.append("No standard files fetched from GitHub. Check repo name, visibility, branch, or token.")

        return observations

    def _request(self, url: str):
        req = urllib.request.Request(url)
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("User-Agent", "atlas-core-github-reader")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        return urllib.request.urlopen(req, timeout=15)

    def _get_json(self, url: str) -> dict | None:
        try:
            with self._request(url) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            return None

    def _fetch_file(self, path: str, ref: str) -> str | None:
        url = f"https://api.github.com/repos/{self.repo_full_name}/contents/{path}?ref={ref}"
        data = self._get_json(url)
        if not data or data.get("type") != "file":
            return None
        content = data.get("content")
        encoding = data.get("encoding")
        if not content or encoding != "base64":
            return None
        try:
            return base64.b64decode(content).decode("utf-8", errors="replace")
        except Exception:
            return None


def _summarize_file(rel: str, text: str, limit: int) -> str:
    lines = text.splitlines()
    head = "\n".join(lines[:80])
    if len(head) > limit:
        head = head[:limit].rstrip() + "..."
    return f"{rel}:\n{head}"
