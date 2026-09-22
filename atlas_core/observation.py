"""Observation.v1 — what was read, from where, and how sure we are of that.

ROADMAP.md P0.1. The whole point of this type is the last part. Phase P0.2 will
decide whether a claim is supported by a source, and it can only do that
against provenance that is either **true** or **honestly absent**. So this
module has one hard rule:

    A field that cannot be verified is set to the literal `"unknown"`.
    It is never filled with a plausible default.

Guessing `ref = "main"` because that is usually right, or letting an empty
string stand in for a missing commit, would make a later verification pass
compare a claim against a source identity nobody established. That is the
failure mode the phase exists to remove, so the constructor rejects the shapes
a guess tends to take — empty strings, whitespace, malformed digests — rather
than storing them.

Two identities live here, and they are deliberately not the same thing:

- `commit` says what was committed. It does **not** identify the bytes that
  were read, because a dirty worktree serves different bytes from the same
  path. `commit_identifies_content()` is true only for a clean worktree.
- `content_sha256` identifies the bytes. It is authoritative on its own, and
  stays so whether or not any provenance field is known.

This module is data only. Reading files and taking snapshots is P0.1b.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Final, Literal

#: The only permitted stand-in for a field that could not be verified.
#: Final so the type checker reads it as Literal["unknown"], which lets it
#: serve as a default for the closed enums below.
UNKNOWN: Final = "unknown"

SCHEMA = "atlas-observation.v1"

SourceType = Literal["local_file", "github_file", "ci", "memory"]
Confidentiality = Literal["public", "internal", "secret", "unknown"]
WorktreeState = Literal["clean", "dirty", "unknown"]

SOURCE_TYPES: tuple[str, ...] = ("local_file", "github_file", "ci", "memory")
CONFIDENTIALITY_CLASSES: tuple[str, ...] = ("public", "internal", "secret", UNKNOWN)
WORKTREE_STATES: tuple[str, ...] = ("clean", "dirty", UNKNOWN)

#: Fields that may name a provenance value, or say `unknown`, but nothing else.
_PROVENANCE_FIELDS: tuple[str, ...] = ("repo", "ref", "commit", "snapshot_id")

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def derive_source_id(snapshot_id: str, source_type: str, path: str) -> str:
    """A stable id for one source within one snapshot.

    Derived rather than random so a re-run over the same snapshot produces the
    same ids, which is what lets P0.2 check that a finding's `source_id` refers
    to something this run actually read.

    It deliberately does not include the content hash: re-reading a changed
    file is the same *source* carrying new *content*.
    """
    digest = hashlib.sha256(
        "\0".join((snapshot_id, source_type, path)).encode("utf-8")
    ).hexdigest()
    return digest[:16]


@dataclass(frozen=True)
class Observation:
    """One thing that was read, with its provenance.

    Frozen: evidence that can be edited after collection is not evidence.

    Validation lives in `__post_init__`, not in `create()`, so every
    construction path is checked — including `dataclasses.replace`, which calls
    `__init__` directly and would otherwise be a way to write a malformed digest
    or a blank commit into a validated object. `__post_init__` also re-derives
    `source_id` and rejects a mismatch, so an observation cannot be re-pointed
    at a different path while keeping the id that named the old one.
    """

    source_id: str
    source_type: SourceType
    path: str
    collected_at: str
    content_sha256: str
    excerpt: str
    line_start: int
    line_end: int
    snapshot_id: str = UNKNOWN
    repo: str = UNKNOWN
    ref: str = UNKNOWN
    commit: str = UNKNOWN
    worktree_state: WorktreeState = UNKNOWN
    confidentiality: Confidentiality = UNKNOWN
    #: How many lines the source has, when that was established. `None` means
    #: nobody counted — the same discipline the provenance strings apply, and
    #: for the same reason: a plausible number here would let a reader conclude
    #: the excerpt was the whole file.
    #:
    #: It exists because the excerpt is bounded. A claim settled against
    #: `lines 1-80` of a 169-line file is settled about those lines and about
    #: nothing else, and a `source_lacks_literal` verdict there is the case
    #: where the distance matters: the sentence names its range, and a reader
    #: can still summarise it into something false about the file. See
    #: ROADMAP P1.1 and `docs/pinned-repo-review.md`, where that was found by
    #: running the loop against a real repository.
    total_lines: int | None = None

    def __post_init__(self) -> None:
        _check_enum("source_type", self.source_type, SOURCE_TYPES)
        _check_enum("worktree_state", self.worktree_state, WORKTREE_STATES)
        _check_enum("confidentiality", self.confidentiality, CONFIDENTIALITY_CLASSES)

        if not self.path.strip():
            raise ValueError("path must name something")
        _check_contained_path(self.path)
        if not self.collected_at.strip():
            raise ValueError("collected_at must be a timestamp, not blank")

        for name in _PROVENANCE_FIELDS:
            _check_known_or_unknown(name, getattr(self, name))

        _check_digest(self.content_sha256)
        _check_line_range(self.excerpt, self.line_start, self.line_end)
        if self.total_lines is not None:
            if self.total_lines < 0:
                raise ValueError(
                    f"total_lines cannot be negative, got {self.total_lines}"
                )
            if self.line_end > self.total_lines:
                raise ValueError(
                    f"observation covers lines {self.line_start}-{self.line_end} "
                    f"of a source said to have {self.total_lines}; one of the two "
                    "is wrong and a reader cannot tell which"
                )

        expected = derive_source_id(self.snapshot_id, self.source_type, self.path)
        if self.source_id != expected:
            raise ValueError(
                "source_id does not match its snapshot, type and path. Build a "
                "new observation through create() rather than re-pointing one."
            )

    @classmethod
    def create(
        cls,
        *,
        source_type: str,
        path: str,
        collected_at: str,
        content_sha256: str,
        excerpt: str,
        line_start: int,
        line_end: int,
        snapshot_id: str = UNKNOWN,
        repo: str = UNKNOWN,
        ref: str = UNKNOWN,
        commit: str = UNKNOWN,
        worktree_state: str = UNKNOWN,
        confidentiality: str = UNKNOWN,
        total_lines: int | None = None,
    ) -> Observation:
        """Build a validated observation, deriving `source_id` for you."""
        return cls(
            source_id=derive_source_id(snapshot_id, source_type, path),
            source_type=source_type,  # type: ignore[arg-type]
            path=path,
            collected_at=collected_at,
            content_sha256=content_sha256,
            excerpt=excerpt,
            line_start=line_start,
            line_end=line_end,
            snapshot_id=snapshot_id,
            repo=repo,
            ref=ref,
            commit=commit,
            worktree_state=worktree_state,  # type: ignore[arg-type]
            confidentiality=confidentiality,  # type: ignore[arg-type]
            total_lines=total_lines,
        )

    def is_verifiable(self) -> bool:
        """Whether anything can later be checked against this observation.

        Content identity is what verification compares, so an observation with
        no digest can be cited but never confirmed. Provenance being `unknown`
        does not disqualify it: a file read outside any repo still has bytes.
        """
        return self.content_sha256 != UNKNOWN

    def commit_identifies_content(self) -> bool:
        """Whether `commit` describes the bytes that were actually read.

        False for a dirty worktree, and false when the worktree state is
        unknown — an unverified assumption is not a yes.
        """
        return self.commit != UNKNOWN and self.worktree_state == "clean"

    def read_in_full(self) -> bool | None:
        """Whether the excerpt is the whole source. `None` when nobody counted.

        Three values, not two, because "we did not check" and "no, it is
        partial" call for different things from a reader.

        **Both ends.** Reaching the last line is not the same as having the
        file: lines 90-169 of a 169-line source end where the source ends and
        are missing everything before them. `collect_observation` always starts
        at line 1, so nothing here produces such a range today — but
        `Observation` is a public type, a host can build one, and a marker that
        only checks one end would call that source complete. The value this
        supports is a `source_lacks_literal` verdict, where the difference
        between "absent from the file" and "absent from the tail" is the whole
        point.
        """
        if self.total_lines is None:
            return None
        if self.total_lines == 0:
            # An empty source has nothing to miss, and `_excerpt` reports 0-0
            # for one — neither "from line 1" nor a gap.
            return self.line_end == 0
        return self.line_start == 1 and self.line_end >= self.total_lines

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            **asdict(self),
            # Derived rather than stored, so it cannot contradict the range it
            # is about.
            "read_in_full": self.read_in_full(),
        }


def _check_enum(name: str, value: str, allowed: tuple[str, ...]) -> None:
    if value not in allowed:
        raise ValueError(f"{name} must be one of {allowed}, got {value!r}")


def _check_known_or_unknown(name: str, value: str) -> None:
    """A provenance field is a real value or the literal `unknown`.

    Blank and whitespace are rejected because they are how an absent value gets
    smuggled in looking like a present one.
    """
    if value == UNKNOWN:
        return
    if not value.strip():
        raise ValueError(
            f"{name} must be a real value or {UNKNOWN!r}; blank is not a provenance claim"
        )
    if value != value.strip():
        raise ValueError(f"{name} must not be padded with whitespace: {value!r}")


def _check_contained_path(path: str) -> None:
    """A recorded path names something inside the snapshot, or nothing at all.

    An observation is a provenance claim, and `../../etc/passwd` is a claim
    about a file the snapshot does not contain. Refusing it here means no such
    record can exist, which is earlier and cheaper than every later reader
    having to defend itself against one.

    This does not replace containment at the read. A name that is legal now can
    resolve outside the root later — a component becomes a symlink — so
    `integrity.read_within` still refuses at the open. The two cover different
    moments.

    Both path spellings are checked. An observation written on POSIX may be
    re-read on Windows, where `..\\x` is an escape and `C:/x` is absolute, so
    the refusal cannot depend on whichever host happened to construct it.
    """
    for flavour in (PurePosixPath, PureWindowsPath):
        candidate = flavour(path)
        if candidate.is_absolute() or candidate.anchor:
            raise ValueError(
                f"path must be relative to the snapshot root, got {path!r}"
            )
        if ".." in candidate.parts:
            raise ValueError(
                f"path must not step outside the snapshot root, got {path!r}"
            )


def _check_digest(content_sha256: str) -> None:
    if content_sha256 == UNKNOWN:
        return
    if not _SHA256.match(content_sha256):
        raise ValueError(
            "content_sha256 must be 64 lowercase hex characters or "
            f"{UNKNOWN!r}, got {content_sha256!r}"
        )


def _check_line_range(excerpt: str, line_start: int, line_end: int) -> None:
    """An excerpt says which lines it covers; no excerpt covers no lines."""
    if line_start < 0 or line_end < 0:
        raise ValueError("line numbers are 1-based; negative lines do not exist")
    if excerpt:
        if line_start < 1:
            raise ValueError("an excerpt must declare the lines it covers")
        if line_end < line_start:
            raise ValueError(
                f"line range must run forwards, got {line_start}..{line_end}"
            )
    elif line_start or line_end:
        raise ValueError("an empty excerpt cannot cover lines")


__all__ = [
    "UNKNOWN",
    "SCHEMA",
    "Observation",
    "SourceType",
    "Confidentiality",
    "WorktreeState",
    "SOURCE_TYPES",
    "CONFIDENTIALITY_CLASSES",
    "WORKTREE_STATES",
    "derive_source_id",
]
