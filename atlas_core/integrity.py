"""P0.1c: source integrity, and what may leave the machine.

ROADMAP.md P0.1, boxes three and four. Two jobs live here, and the order
between them is the whole design:

1. **Integrity** runs against raw bytes at the original snapshot.
   `snapshot.verify_observation` compares the digest of the full content and
   the excerpt against the line range it claims.
2. **Redaction** runs on the way out, over the whole exported document. The
   patterns themselves live in `redaction`, because collection needs them too:
   a source is classified by what it carries.

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

## Where containment applies

Every read of an observation's path goes through `read_within`:
`collect_observation_safely` at collection, `finding.LocalFileReader` when a
citation is checked, and `snapshot.verify_observation` when an observation is
re-verified. `Observation.path` also refuses `../` and absolute forms at
construction, so a record naming a file outside its snapshot cannot exist in
the first place. The two layers cover different moments — a name that is legal
when recorded can resolve outside the root later.

## What this does not cover

- Resolving a name and opening a file are two steps, and `resolve_within`
  answers a question about the *name*. `read_within` is the open-side half:
  it opens with `O_NOFOLLOW`, so the kernel refuses at descriptor creation if
  the final component has become a symlink since the name was checked, and it
  reads through that descriptor instead of walking the path again. A
  demonstration of the unprotected version reading a file outside the root is
  in the test suite.
  What remains open: a **directory** component of the path can still be
  replaced by a link between the resolve and the open, which would need an
  `openat` walk per component (or Linux `openat2(RESOLVE_BENEATH)`, which
  Python does not expose) to close. And content can always change between one
  check and a later one; integrity is re-established by re-verifying, never
  assumed.
- Detection is narrow, by design. `redaction` matches credential shapes, home
  directories and email addresses; arbitrary personal data is not recognised.
  That limit is why `classify_confidentiality` never answers `public`: no match
  is a statement about the patterns, not about the source.

Not in scope: `Finding.v1` and semantic verification are P0.2. Nothing here
decides whether a claim is true.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .containment import PathRefused, read_within, resolve_within
from .observation import UNKNOWN, Observation
from .redaction import REDACTED, VERBATIM_KEYS, redact_document, redact_text
from .snapshot import Snapshot, collect_observation, verify_observation


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
    `redaction.VERBATIM_KEYS`.

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
        entries.append(redact_document(entry))

    return {
        "schema": "atlas-observation-manifest.v1",
        "snapshot": redact_document(
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


__all__ = [
    "REDACTED",
    "PathRefused",
    "collect_observation_safely",
    "read_within",
    "redact_text",
    "redacted_manifest",
    "resolve_within",
]
