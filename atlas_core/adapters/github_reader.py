from __future__ import annotations

import base64
import json
import os
import re
from time import monotonic
from urllib.parse import quote
import urllib.error
import urllib.request

from ..budget import BudgetExceeded, RunBudget

CANDIDATE_FILES = [
    "README.md", "pyproject.toml", "package.json", "docs/architecture.md",
    "docs/CONTEXT_CONTRACT.md", "docs/TOKEN_BUDGET.md",
    "docs/context-export-contract.md", "docs/memory-model.md",
    "docs/roadmap-token-reduction.md", ".github/workflows/test.yml",
    ".github/workflows/run-atlas.yml",
]


class GitHubRepoAdapter:
    """Fixed-surface GitHub GET reader; bounded mode refuses network ambiguity."""

    def __init__(self, repo_full_name: str, ref: str | None = None, max_chars_per_file: int = 1200):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo_full_name):
            raise ValueError("repo_full_name must be in owner/name form")
        if not isinstance(max_chars_per_file, int) or max_chars_per_file < 1:
            raise ValueError("max_chars_per_file must be positive")
        self.repo_full_name = repo_full_name
        self.ref = ref
        self.max_chars_per_file = max_chars_per_file
        self.token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")

    def observe(self, task: str, *, budget: RunBudget | None = None) -> list[str]:
        observations: list[str] = [f"GitHub repo: {self.repo_full_name}"]
        meta = self._get_json(f"https://api.github.com/repos/{self.repo_full_name}", budget=budget)
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
            if budget is not None:
                raise RuntimeError("repository metadata unavailable in bounded mode")
            default_branch = "main"
            observations.append("Repo metadata could not be fetched. Continuing with default branch assumption: main.")

        ref = quote(str(self.ref or default_branch), safe="")
        found = 0
        for rel in CANDIDATE_FILES:
            if budget is not None:
                budget.check()
            text = self._fetch_file(rel, ref, budget=budget)
            if text is None:
                continue
            found += 1
            observations.append(_summarize_file(rel, text, self.max_chars_per_file))
        if found == 0:
            if budget is not None:
                raise RuntimeError("no standard GitHub files available in bounded mode")
            observations.append("No standard files fetched from GitHub. Check repo name, visibility, branch, or token.")
        return observations

    def _request(self, url: str, *, timeout: float = 15.0):
        req = urllib.request.Request(url)
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("User-Agent", "atlas-core-github-reader")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        return urllib.request.urlopen(req, timeout=timeout)

    def _get_json(self, url: str, *, budget: RunBudget | None = None,
                  missing_is_ok: bool = False) -> dict | None:
        try:
            timeout = 15.0
            if budget is not None:
                budget.reserve_tool()
                timeout = min(15.0, max(0.001, budget.deadline - monotonic()))
            with self._request(url, timeout=timeout) as response:
                if budget is None:
                    raw = response.read()
                else:
                    # A tiny excerpt does not justify an unlimited HTTP body.
                    max_bytes = max(4096, min(2_000_000, budget.limits.output_bytes * 4))
                    raw = response.read(max_bytes + 1)
                    if len(raw) > max_bytes:
                        raise BudgetExceeded("output_bytes")
                    budget.check()
                data = json.loads(raw.decode("utf-8"))
                if not isinstance(data, dict):
                    raise TypeError("GitHub API returned a non-object")
                return data
        except urllib.error.HTTPError as exc:
            if missing_is_ok and exc.code == 404:
                return None
            if budget is None:
                return None
            raise RuntimeError(f"GitHub HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError,
                UnicodeDecodeError, TypeError) as exc:
            if budget is None:
                return None
            raise RuntimeError("GitHub observation failed") from exc

    def _fetch_file(self, path: str, ref: str, *, budget: RunBudget | None = None) -> str | None:
        url = f"https://api.github.com/repos/{self.repo_full_name}/contents/{path}?ref={ref}"
        data = self._get_json(url, budget=budget, missing_is_ok=True)
        if not data or data.get("type") != "file":
            return None
        content = data.get("content")
        if not content or data.get("encoding") != "base64":
            if budget is not None:
                raise RuntimeError("GitHub file encoding missing or invalid")
            return None
        try:
            return base64.b64decode(content, validate=True).decode("utf-8", errors="replace")
        except (ValueError, TypeError) as exc:
            if budget is not None:
                raise RuntimeError("GitHub content decoding failed") from exc
            return None


def _summarize_file(rel: str, text: str, limit: int) -> str:
    lines = text.splitlines()
    head = "\n".join(lines[:80])
    if len(head) > limit:
        head = head[:limit].rstrip() + "..."
    return f"{rel}:\n{head}"
