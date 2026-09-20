"""P0.1c: source integrity, and what may leave the machine.

ROADMAP.md P0.1, boxes three and four. Two jobs live here, and the order
between them is the whole design:

1. **Integrity** runs against raw bytes at the original snapshot.
   `snapshot.verify_observation` compares the digest of the full content and
   the excerpt against the line range it claims.
2. **Redaction** runs on the way out, over the excerpt only.

Redaction touches neither `content_sha256` nor the stored excerpt. The digest
is taken over raw content, and the excerpt an observation carries stays raw so
it can be compared against the lines it claims — raw sources remain local, as
the roadmap requires. Masking produces a *view*, in `redacted_manifest`.

This order was not obvious. Masking the excerpt at collection time looked
tidier, and a test in this suite showed what it costs: the masked excerpt no
longer matches the file, so an untouched source verifies as `stale`. The tests
now assert that building the redacted view moves neither the digest nor the
verdict.

Path handling is refusal, not sanitisation. `resolve_within` resolves symlinks
first and then requires the result to be inside the snapshot root, so a link
pointing outside is refused rather than followed and trimmed. Refusing is the
safe failure: a path that tries to escape is a bug or an attack, and neither
deserves a best-effort read.

## What this does not cover

Path containment protects the read paths that go through
`collect_observation_safely`. It is **not** a property of every read:

- `snapshot.verify_observation` re-reads `root / observation.path` with no
  containment check of its own, and `Observation.path` is a plain string that
  today accepts `../` and absolute forms. A finding checker that re-reads a
  source has to do its own safe read; relying on the collection wrapper to
  have covered it would be wrong.
- Even on the safe path, resolving and then reading are two steps. Reading
  through the resolved concrete path removes symlink swapping between them,
  but a file can still change between any check and any later read. Integrity
  is re-established by re-verifying, not assumed from an earlier check.
- Redaction is best-effort. It masks credential shapes, home directories and
  email addresses. It does not detect arbitrary personal data, and nothing
  here classifies it.

The full P0.1 security box stays open for those reasons.

Not in scope: `Finding.v1` and semantic verification are P0.2. Nothing here
decides whether a claim is true.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .observation import UNKNOWN, Observation
from .snapshot import Snapshot, collect_observation, verify_observation

#: What replaces a masked span. Distinctive so a reader can tell masking from
#: content, and stable so redaction is idempotent.
REDACTED = "[REDACTED]"


class PathRefused(Exception):
    """A path resolved outside the snapshot root, or tried to.

    Raised rather than clamped. Silently reading a different file than the one
    requested is worse than failing.
    """


# Ordered most specific first: a private key header must not be half-matched by
# a looser rule. Each pattern targets a shape that is a secret by construction,
# not merely a long string, so ordinary prose and hex digests survive.
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    # A private key is a block, not a line. Masking only the BEGIN header left
    # the key body and END line in the clear. The first pattern takes a
    # complete block; the second covers a header whose END is missing, by
    # consuming the base64 run that follows it.
    re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"
    ),
    re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----(?:\s*\n[A-Za-z0-9+/]{16,}={0,2})*"
    ),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"sk-ant-[A-Za-z0-9-]{20,}"),
    re.compile(r"sk-[A-Za-z0-9]{32,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
)

#: A home directory names a person and a machine. The tail is kept because the
#: fact that `.ssh/id_rsa` was read is exactly the context a reviewer needs.
_HOME_PATH = re.compile(r"(?:/Users|/home)/[^/\s]+")

_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")


def resolve_within(root: str | Path, relative_path: str) -> Path:
    """Resolve `relative_path` under `root`, refusing anything that escapes.

    Symlinks are resolved *before* the containment check, so a link inside the
    root pointing outside it is refused. A link that stays inside is fine —
    the rule is about where bytes come from, not about links.
    """
    resolved_root = Path(root).expanduser().resolve()
    candidate = Path(relative_path)

    if candidate.is_absolute():
        raise PathRefused(f"absolute paths are not read from a snapshot: {relative_path!r}")

    target = (resolved_root / candidate).resolve()

    # relative_to, not a string prefix: "/tmp/root-evil" starts with
    # "/tmp/root" but is a different directory.
    try:
        target.relative_to(resolved_root)
    except ValueError:
        raise PathRefused(
            f"{relative_path!r} resolves to {target}, outside the snapshot root"
        ) from None
    return target


def collect_observation_safely(
    snapshot: Snapshot, relative_path: str, **kwargs: Any
) -> Observation:
    """Collect an observation, refusing any path that escapes the snapshot.

    Reads through the **resolved** path rather than the string it was asked
    for. Checking one path and then reading another is how a check gets
    bypassed: a symlink inside the root can be repointed between the two. The
    recorded `path` is therefore the concrete file, which is also more honest
    provenance than the alias used to reach it.

    The excerpt stays **raw**. Raw sources remain local, and verification
    compares the excerpt against the lines it claims — masking here would make
    an untouched source read as `stale`, which a test in this suite
    demonstrated before the split was made explicit. Masking happens on the way
    out, in `redacted_manifest`.

    This is not blanket protection for every read path. See the module
    docstring.
    """
    resolved = resolve_within(snapshot.root, relative_path)
    concrete = resolved.relative_to(Path(snapshot.root).expanduser().resolve())
    return collect_observation(snapshot, concrete.as_posix(), **kwargs)


def redact_text(text: str) -> str:
    """Mask credentials, home paths and email addresses.

    Deliberately narrow. Masking anything that merely looks sensitive would cut
    away the context a reviewer needs to check a claim, which the roadmap calls
    out directly. Hex digests, commit ids, versions and file paths inside the
    repo are left alone.
    """
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(REDACTED, text)
    text = _HOME_PATH.sub(REDACTED, text)
    return _EMAIL.sub(REDACTED, text)


#: Fields that leave the export verbatim. Everything else is masked.
#:
#: The digest and the ids are the pointer a reader follows back to what was
#: verified; masking them would break the manifest's only job. They are also
#: structurally incapable of carrying prose — hex digests and enum values —
#: so exempting them costs nothing.
_VERBATIM_KEYS: frozenset[str] = frozenset(
    {
        "schema",
        "source_id",
        "snapshot_id",
        "content_sha256",
        "commit",
        "source_type",
        "worktree_state",
        "confidentiality",
        "verification",
        "is_evidence",
        "line_start",
        "line_end",
        "collected_at",
        "taken_at",
    }
)


def redacted_manifest(
    snapshot: Snapshot,
    observations: list[Observation],
    *,
    root: str | Path | None = None,
) -> dict[str, Any]:
    """Build the exportable record of what a run read.

    Masking covers the **whole** export, not just the excerpt. A path like
    `docs/privat@example.com.md` or a branch name carrying token-shaped text
    leaves a run through metadata just as readily as through content, so every
    exported string is masked except the verification pointer itself —
    `content_sha256`, the ids, and the structural enums, listed in
    `_VERBATIM_KEYS`.

    The digest stays verbatim on purpose: the manifest exists to point at what
    was verified, and a masked digest points at nothing.

    When `root` is given, each entry is re-verified so the manifest states
    whether the source still backs it rather than leaving a reader to assume.
    """
    entries: list[dict[str, Any]] = []
    for observation in observations:
        entry: dict[str, Any] = {
            **observation.to_dict(),
            "verification": UNKNOWN,
            "is_evidence": False,
        }
        if root is not None:
            verification = verify_observation(observation, root)
            entry["verification"] = verification.result
            entry["is_evidence"] = verification.is_evidence()
        entries.append(_redact_export(entry))

    return {
        "schema": "atlas-observation-manifest.v1",
        "snapshot": _redact_export(
            {
                "snapshot_id": snapshot.snapshot_id,
                "taken_at": snapshot.taken_at,
                "commit": snapshot.commit,
                "ref": snapshot.ref,
                "worktree_state": snapshot.worktree_state,
            }
        ),
        "observations": entries,
    }


def _redact_export(document: dict[str, Any]) -> dict[str, Any]:
    """Mask every string in an exported document except the pointer fields."""
    return {
        key: value
        if key in _VERBATIM_KEYS or not isinstance(value, str)
        else redact_text(value)
        for key, value in document.items()
    }


__all__ = [
    "REDACTED",
    "PathRefused",
    "collect_observation_safely",
    "redact_text",
    "redacted_manifest",
    "resolve_within",
]
