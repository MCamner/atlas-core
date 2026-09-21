"""What counts as sensitive, and what a document looks like on the way out.

ROADMAP.md P0.1, box four. This module holds one thing: the patterns that say
what content is sensitive, plus the two operations built on them.

- `classify_confidentiality` reads content and says how sensitive it is. It
  runs at **collection** time, so a source is labelled by what it carries
  rather than staying `unknown` because nobody said otherwise.
- `redact_text` and `redact_document` mask on the way **out**, so raw sources
  stay local.

The two callers sit on opposite sides of the package — `snapshot` collects,
`integrity` and `state` export — which is why the patterns live here rather
than in either. Nothing in this module imports from the rest of Atlas Core.

## Why classification never returns `public`

The detection is deliberately narrow: it matches credential shapes, home
directories and email addresses, and nothing else. So a match is real evidence
that content is sensitive, and *no* match is evidence of nothing at all. A
classifier that answered `public` on no match would be converting the limits of
its own patterns into a claim about the source, which is the kind of unearned
confidence the whole phase exists to remove. `unknown` is the honest answer,
and a caller who knows better may state a class and is not overruled.

## Why redaction is narrow

Masking anything that merely looks sensitive would cut away the context a
reviewer needs to check a claim — the roadmap says so directly. Hex digests,
commit ids, versions and repository-relative paths are left alone.
"""

from __future__ import annotations

import re
from typing import Any, Literal

#: What replaces a masked span. Distinctive so a reader can tell masking from
#: content, and stable so redaction is idempotent.
REDACTED = "[REDACTED]"

Confidentiality = Literal["public", "internal", "secret", "unknown"]

# Ordered most specific first: a private key header must not be half-matched by
# a looser rule. Each pattern targets a shape that is a secret by construction,
# not merely a long string, so ordinary prose and hex digests survive.
SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
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
HOME_PATH = re.compile(r"(?:/Users|/home)/[^/\s]+")

EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")

#: Fields that leave an export verbatim. Everything else is masked.
#:
#: The digest and the ids are the pointer a reader follows back to what was
#: verified; masking them would break the manifest's only job. They are also
#: structurally incapable of carrying prose — hex digests and enum values —
#: so exempting them costs nothing.
VERBATIM_KEYS: frozenset[str] = frozenset(
    {
        "schema",
        "source_id",
        "snapshot_id",
        "finding_id",
        "run_id",
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
        "created_at",
        "status",
        "stop_reason",
        "stop_class",
        "state_machine",
        "verdict",
        "verification_method",
    }
)


def classify_confidentiality(text: str) -> Confidentiality:
    """How sensitive this content is, judged only by what it contains.

    `secret` when a credential shape is present, `internal` when personal data
    is, and `unknown` otherwise. Never `public`: see the module docstring.

    A credential outranks personal data, because the stronger finding is the
    one that has to govern how the source is handled.
    """
    if any(pattern.search(text) for pattern in SECRET_PATTERNS):
        return "secret"
    if HOME_PATH.search(text) or EMAIL.search(text):
        return "internal"
    return "unknown"


def redact_text(text: str) -> str:
    """Mask credentials, home paths and email addresses."""
    for pattern in SECRET_PATTERNS:
        text = pattern.sub(REDACTED, text)
    text = HOME_PATH.sub(REDACTED, text)
    return EMAIL.sub(REDACTED, text)


def redact_document(value: Any, *, verbatim_keys: frozenset[str] = VERBATIM_KEYS) -> Any:
    """Mask every string in a document, except under a verbatim key.

    Recursive, because a run document is not flat: the prose observation
    channel, the produced outputs and each evaluation's claims are lists and
    nested objects, and a masker that only walked the top level would leave
    exactly those in the clear. Non-strings are returned unchanged — a number
    cannot carry a secret, and coercing one would corrupt the document.
    """
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {
            key: value[key]
            if key in verbatim_keys
            else redact_document(value[key], verbatim_keys=verbatim_keys)
            for key in value
        }
    if isinstance(value, (list, tuple)):
        return [redact_document(item, verbatim_keys=verbatim_keys) for item in value]
    return value


__all__ = [
    "EMAIL",
    "HOME_PATH",
    "REDACTED",
    "SECRET_PATTERNS",
    "VERBATIM_KEYS",
    "Confidentiality",
    "classify_confidentiality",
    "redact_document",
    "redact_text",
]
