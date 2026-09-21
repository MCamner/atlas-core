"""Where a read may go, and what it refuses.

ROADMAP.md P0.1, box four. Containment is the other half of `redaction`: one
says what may leave, this says what may be read at all. Both are leaves — they
import nothing from the rest of Atlas Core — because both are needed *below*
the layer that collects observations as well as above it. `snapshot` re-reads a
source to verify it, and that read has to be contained too; a module that could
only be used by the export layer would have left the verification read
unprotected, which is exactly the gap this closes.

Path handling is refusal, not sanitisation. `resolve_within` resolves symlinks
first and then requires the result to be inside the snapshot root, so a link
pointing outside is refused rather than followed and trimmed. Refusing is the
safe failure: a path that tries to escape is a bug or an attack, and neither
deserves a best-effort read.

What remains open is in `integrity`'s module docstring.
"""

from __future__ import annotations

import errno
import os
from pathlib import Path


class PathRefused(Exception):
    """A path resolved outside the snapshot root, or tried to.

    Raised rather than clamped. Silently reading a different file than the one
    requested is worse than failing.
    """


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


def read_within(root: str | Path, relative_path: str) -> str:
    """Read a file under `root`, refusing an escape *at the open*.

    `resolve_within` settles where a name points. Between that answer and an
    open, the concrete file it named can be replaced by a symlink pointing out
    of the root, and the read then serves bytes from outside while the earlier
    check still reads as passed. `O_NOFOLLOW` moves the refusal into the same
    operation that produces the descriptor, and the content comes from that
    descriptor rather than from a second walk of the path.

    Raises `PathRefused` for a name that escapes or a final component that has
    become a link, and `OSError` for an ordinary read failure — a caller needs
    to tell "refused" from "gone".

    This narrows the window; it does not close it. See the module docstring.
    """
    path = resolve_within(root, relative_path)
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as error:
        if error.errno in (errno.ELOOP, errno.EMLINK):
            raise PathRefused(
                f"{relative_path!r} became a symbolic link before it could be read"
            ) from None
        raise
    with os.fdopen(descriptor, encoding="utf-8", errors="replace") as handle:
        return handle.read()
