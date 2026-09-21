"""P0.1b: take a snapshot, collect observations against it, detect drift.

ROADMAP.md P0.1, second box. Three jobs, kept apart on purpose:

- `take_snapshot` establishes *what state was read*. It asks git for a commit,
  a ref and whether the worktree is dirty, and says `unknown` for anything it
  cannot establish — there is no git, git failed, or the path is not a repo.
- `collect_observation` reads one file and records it as an `Observation.v1`.
  It hashes the **full content** and keeps a bounded excerpt, so trimming the
  excerpt never moves the identity that verification compares.
- `verify_observation` reads the source again and answers whether the
  observation still describes it.

The last one carries the phase's point. `fresh` is the only outcome that counts
as evidence; `stale`, `missing` and `unverifiable` do not, and
`Verification.is_evidence()` is the single place that decides.

A dirty worktree is the case that motivates keeping snapshot identity separate
from commit identity: the commit is real, and it still does not tell you which
bytes were served from that path.

`detect_drift` is what the controller calls. A run grades its answer and then
asks whether the state it read still holds; if it does not, the run stops
`blocked` and says what moved. The loop keeps its `list[str]` observations as a
separate prose channel — see `evidence_base` for why those two are not the same
thing and why neither converts into the other.
"""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from .containment import PathRefused, read_within
from .observation import UNKNOWN, Observation, WorktreeState
from .redaction import classify_confidentiality

#: Excerpts are bounded so a manifest stays reviewable. The digest is taken
#: over the whole file, so this bound never weakens verification.
DEFAULT_MAX_LINES = 80

VerificationResult = Literal["fresh", "stale", "missing", "refused", "unverifiable"]

_GIT_TIMEOUT = 10


@dataclass(frozen=True)
class Snapshot:
    """The state a run read from, and how much of it could be established."""

    snapshot_id: str
    root: str
    taken_at: str
    commit: str = UNKNOWN
    ref: str = UNKNOWN
    worktree_state: WorktreeState = UNKNOWN

    def has_moved(self) -> bool:
        """Whether the *state* changed since this snapshot was taken.

        This compares HEAD and clean/dirty, not file contents. Two limits
        follow, and both are real:

        - An already-dirty worktree whose files change again stays dirty at the
          same commit, so this returns False while the content has moved.
        - A snapshot that could not establish its state cannot tell that the
          state changed, so this returns False there too.

        Content drift is caught by `verify_observation`. Use `detect_drift` for
        the question the roadmap actually asks — did HEAD *or a file* move
        during the read — because it checks both.
        """
        current = take_snapshot(self.root)
        return current.snapshot_id != self.snapshot_id


@dataclass(frozen=True)
class Verification:
    """The answer to "does this observation still describe its source?"."""

    result: VerificationResult
    reason: str
    observed_sha256: str

    def is_evidence(self) -> bool:
        """Only a fresh observation may back a claim.

        Step 7 of the P0.1 Definition of Done lives here, in one place, so no
        caller gets to decide that a stale source is close enough.
        """
        return self.result == "fresh"


@dataclass(frozen=True)
class DriftReport:
    """Whether a run's reads describe one consistent state.

    `has_moved` alone is not enough: it sees HEAD and clean/dirty, so an
    already-dirty worktree can change underneath a read without moving. This
    pairs that state check with a per-source content check, which is the
    roadmap's "upptäck ändrad HEAD/fil under läsning".
    """

    head_moved: bool
    #: Everything that is no longer fresh, keyed by source_id.
    not_evidence: dict[str, Verification]

    def is_consistent(self) -> bool:
        return not self.head_moved and not self.not_evidence


def verify_all(
    observations: list[Observation], root: str | Path
) -> dict[str, Verification]:
    """Re-check every observation against the source it came from."""
    return {
        observation.source_id: verify_observation(observation, root)
        for observation in observations
    }


def detect_drift(snapshot: Snapshot, observations: list[Observation]) -> DriftReport:
    """Did HEAD or any read file move since these observations were collected?"""
    verifications = verify_all(observations, snapshot.root)
    return DriftReport(
        head_moved=snapshot.has_moved(),
        not_evidence={
            source_id: verification
            for source_id, verification in verifications.items()
            if not verification.is_evidence()
        },
    )


def take_snapshot(root: str | Path) -> Snapshot:
    """Establish what state `root` is in, admitting what cannot be established."""
    resolved = Path(root).expanduser().resolve()
    commit = _git(resolved, "rev-parse", "HEAD")
    ref = _git(resolved, "rev-parse", "--abbrev-ref", "HEAD")
    worktree_state = _worktree_state(resolved, commit)

    return Snapshot(
        snapshot_id=_derive_snapshot_id(resolved, commit, worktree_state),
        root=str(resolved),
        taken_at=datetime.now(timezone.utc).isoformat(),
        commit=commit,
        ref=ref,
        worktree_state=worktree_state,
    )


def collect_observation(
    snapshot: Snapshot,
    relative_path: str,
    *,
    max_lines: int = DEFAULT_MAX_LINES,
    confidentiality: str | None = None,
) -> Observation:
    """Read one file under the snapshot and record it with its provenance.

    Raises `FileNotFoundError` rather than returning an observation with an
    `unknown` digest: a file that is not there was not read, and recording it
    as a source would be the fabrication this phase exists to prevent.

    `confidentiality` is derived from the content when the caller states
    nothing, rather than staying `unknown` because nobody filled it in. It is
    classified from the **full** content, not the excerpt, so a credential
    below the excerpt bound still marks the source. A caller that states a
    class is not overruled: someone who knows the source knows more than a
    pattern does.
    """
    path = Path(snapshot.root) / relative_path
    content = path.read_text(encoding="utf-8", errors="replace")
    excerpt, line_start, line_end = _excerpt(content, max_lines)
    if confidentiality is None:
        confidentiality = classify_confidentiality(content)

    return Observation.create(
        source_type="local_file",
        path=relative_path,
        collected_at=datetime.now(timezone.utc).isoformat(),
        content_sha256=sha256_text(content),
        excerpt=excerpt,
        line_start=line_start,
        line_end=line_end,
        snapshot_id=snapshot.snapshot_id,
        commit=snapshot.commit,
        ref=snapshot.ref,
        worktree_state=snapshot.worktree_state,
        confidentiality=confidentiality,
    )


def verify_observation(observation: Observation, root: str | Path) -> Verification:
    """Read the source again and report whether the observation still holds.

    Both the full-content digest and the quoted line range are checked. The
    digest alone would miss an excerpt that no longer matches the lines it
    claims, and the range alone would miss a change elsewhere in the file that
    a later claim might depend on.
    """
    if not observation.is_verifiable():
        return Verification(
            result="unverifiable",
            reason="observation carries no content digest",
            observed_sha256=UNKNOWN,
        )

    if observation.source_type != "local_file":
        # A `ci` path is `ci://provider/workflow@ref`, and a `github_file` path
        # names a file in another checkout. Joining either onto this root would
        # either miss or, worse, hit an unrelated local file and report on it.
        # Those sources are re-read through their own adapter; see
        # `finding.SourceReader`.
        return Verification(
            result="unverifiable",
            reason=f"a {observation.source_type} source is not re-read from the snapshot root",
            observed_sha256=UNKNOWN,
        )

    # Containment belongs to this read. The path was refused at construction if
    # it named an escape, but a component can become a symlink out of the root
    # afterwards, and re-verification is exactly the moment that matters.
    try:
        content = read_within(root, observation.path)
    except PathRefused as refusal:
        return Verification(
            result="refused",
            reason=str(refusal),
            observed_sha256=UNKNOWN,
        )
    except (FileNotFoundError, NotADirectoryError, IsADirectoryError):
        return Verification(
            result="missing",
            reason=f"{observation.path} is no longer readable",
            observed_sha256=UNKNOWN,
        )

    observed = sha256_text(content)
    if observed != observation.content_sha256:
        return Verification(
            result="stale",
            reason="content digest does not match what was observed",
            observed_sha256=observed,
        )

    if _lines(content, observation.line_start, observation.line_end) != observation.excerpt:
        return Verification(
            result="stale",
            reason="excerpt no longer matches the line range it claims",
            observed_sha256=observed,
        )

    return Verification(
        result="fresh",
        reason="content digest and line range both match",
        observed_sha256=observed,
    )


def sha256_text(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _derive_snapshot_id(root: Path, commit: str, worktree_state: str) -> str:
    """Identity of the state, not of the moment it was read.

    Deterministic so the same unchanged checkout yields the same snapshot, and
    so a re-read is recognisably the same source. A dirty worktree still gets a
    stable id — `worktree_state` is what says the id does not pin the bytes,
    and `content_sha256` is what actually does.
    """
    digest = hashlib.sha256(
        "\0".join((str(root), commit, worktree_state)).encode("utf-8")
    ).hexdigest()
    return digest[:16]


def _worktree_state(root: Path, commit: str) -> WorktreeState:
    if commit == UNKNOWN:
        return UNKNOWN
    status = _git(root, "status", "--porcelain")
    if status == UNKNOWN:
        return UNKNOWN
    return "dirty" if status else "clean"


def _git(root: Path, *args: str) -> str:
    """Ask git, and return `unknown` rather than a guess when it cannot say."""
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
            timeout=_GIT_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        return UNKNOWN
    if completed.returncode != 0:
        return UNKNOWN
    return completed.stdout.strip()


def _excerpt(content: str, max_lines: int) -> tuple[str, int, int]:
    if max_lines < 1:
        raise ValueError("max_lines must be at least 1")
    lines = content.splitlines()
    if not lines:
        return "", 0, 0
    kept = lines[:max_lines]
    return "\n".join(kept), 1, len(kept)


def _lines(content: str, line_start: int, line_end: int) -> str:
    if line_start < 1:
        return ""
    return "\n".join(content.splitlines()[line_start - 1 : line_end])


__all__ = [
    "DEFAULT_MAX_LINES",
    "DriftReport",
    "Snapshot",
    "Verification",
    "VerificationResult",
    "collect_observation",
    "detect_drift",
    "sha256_text",
    "take_snapshot",
    "verify_all",
    "verify_observation",
]
