from __future__ import annotations

from itertools import zip_longest
from pathlib import Path, PurePosixPath

from ..budget import RunBudget
from ..containment import PathRefused, SourceTooLarge, resolve_within
from ..integrity import collect_observation_safely
from ..observation import Observation
from ..observer import ObservationRequest

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


#: Per-source hard limit. The digest covers the whole source, so a larger file
#: is refused rather than cut: a truncated read would hash bytes that are not
#: the file.
DEFAULT_MAX_BYTES_PER_FILE = 256 * 1024
#: Per-round limit on how many sources one request may resolve to. A pattern
#: such as `tests/*` can match far more files than a question needs. Patterns
#: take turns, in sorted order within each, so every pattern with a match gets
#: a read before any gets a second; the round says each pattern was answered.
DEFAULT_MAX_FILES_PER_ROUND = 8


class FilesystemRepoObserver:
    """The host half of `Observer` for one local checkout.

    Core names what it needs — paths to read again, patterns from the review
    plan — and this reads them as `Observation.v1` bound to the request's
    snapshot. A first request that names nothing gets the same fixed surface
    `FilesystemRepoAdapter` reads, so an un-narrowed task still has sources.

    Every read reserves a tool call on the run's budget and is checked against
    it, goes through `collect_observation_safely` (contained name, `O_NOFOLLOW`
    open) and is bounded by `max_bytes_per_file`. A source that is refused,
    too large, missing or not a file is skipped: it was not read, so it is not
    evidence, and a path already in the run that stops reading keeps failing
    the drift gate instead of silently passing.
    """

    def __init__(
        self,
        repo_path: str | Path,
        *,
        max_bytes_per_file: int = DEFAULT_MAX_BYTES_PER_FILE,
        max_files_per_round: int = DEFAULT_MAX_FILES_PER_ROUND,
    ) -> None:
        self.repo_path = Path(repo_path).expanduser().resolve()
        if max_bytes_per_file < 1 or max_files_per_round < 1:
            raise ValueError("per-file and per-round limits must be positive")
        self.max_bytes_per_file = max_bytes_per_file
        self.max_files_per_round = max_files_per_round

    def observe(
        self, request: ObservationRequest, *, budget: RunBudget
    ) -> list[Observation]:
        root = Path(request.snapshot.root).expanduser().resolve()
        if root != self.repo_path:
            raise ValueError("the request's snapshot is not this repository")
        # Paths already in the run first: they are what the drift gate needs.
        # Then the patterns round-robin, so a pattern that matches many files
        # cannot use up the round before another pattern gets one read — a
        # pattern this round came back from counts as answered.
        reread = _present(root, list(request.paths))
        by_pattern = [_present(root, _matching(root, p)) for p in request.patterns]
        if not request.paths and not request.patterns:
            by_pattern = [_present(root, CANDIDATE_FILES)]
        wanted = reread + [
            name for rank in zip_longest(*by_pattern) for name in rank if name is not None
        ]
        observations: list[Observation] = []
        seen: set[str] = set()
        for relative in list(dict.fromkeys(wanted))[: self.max_files_per_round]:
            budget.check()
            budget.reserve_tool()
            try:
                observation = collect_observation_safely(
                    request.snapshot, relative, max_bytes=self.max_bytes_per_file
                )
            except (PathRefused, SourceTooLarge, OSError):
                # Refused, too large, gone or unreadable (a permission, say):
                # not read, so not evidence. One such file must not end the
                # run's reading of the rest.
                continue
            budget.check()
            # Two names for one file (a link inside the root) resolve to the
            # same source; a round may carry each source once.
            if observation.source_id not in seen:
                seen.add(observation.source_id)
                observations.append(observation)
        return observations


def _present(root: Path, names: list[str]) -> list[str]:
    """The names that are files inside `root`.

    A name that is not one costs nothing: resolving and a stat are not a read,
    and a quota spent on absent files — or on links out of the root, which
    the read would refuse anyway — is a quota lost.
    """
    present: list[str] = []
    for name in names:
        try:
            if resolve_within(root, name).is_file():
                present.append(name)
        except (PathRefused, OSError):
            continue
    return present


def _matching(root: Path, pattern: str) -> list[str]:
    """Files under `root` that one plan pattern names, sorted.

    Not recursive: `**` is refused, as are absolute and `..` patterns. A plan
    names at most a handful of shallow patterns, and a pattern that could walk
    the whole tree is not a question.
    """
    parts = PurePosixPath(pattern).parts
    if not parts or pattern.startswith("/") or ".." in parts or "**" in pattern:
        return []
    return sorted(
        path.relative_to(root).as_posix()
        for path in root.glob(pattern)
        if path.is_file()
    )
