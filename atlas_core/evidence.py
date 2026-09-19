"""Which claims in an output are traceable to something that was actually read.

The evaluator uses this to grade whether a finding is supported, rather than
whether it is well formatted. Nothing here interprets meaning: it matches
finding text against the source labels the adapters put in the observation
list. That is deliberately shallow — it can tell that a finding cites no
source at all, which is the failure mode worth catching, and it never claims
to have checked that a cited finding is *true*.
"""

from __future__ import annotations

# Adapters emit observations as "<relative path>:\n<content head>". mqobsidian
# prefixes a provenance line first, so the path line is not always line one.
_MEMORY_PREFIX = "Durable memory"


def observed_sources(observations: list[str] | None) -> list[str]:
    """Return the source labels a finding may legitimately cite.

    Durable memory is excluded on purpose. `docs/safety-model.md` states that
    memory is context rather than current runtime truth, so a claim about how a
    repository looks now cannot be verified by it.
    """
    sources: list[str] = []
    for observation in observations or []:
        if observation.startswith(_MEMORY_PREFIX):
            continue
        label = _source_label(observation)
        if label and label not in sources:
            sources.append(label)
    return sources


def _source_label(observation: str) -> str | None:
    for line in observation.splitlines():
        line = line.strip()
        if not line.endswith(":"):
            continue
        candidate = line[:-1].strip()
        if _looks_like_a_path(candidate):
            return candidate
    return None


def _looks_like_a_path(candidate: str) -> bool:
    if not candidate or " " in candidate:
        return False
    return "/" in candidate or "." in candidate


def findings_in(output: str, headings: tuple[str, ...]) -> list[str]:
    """Return the bullet text under any of the given headings."""
    findings: list[str] = []
    collecting = False
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            collecting = any(stripped.startswith(heading) for heading in headings)
            continue
        if collecting and stripped.startswith("- "):
            findings.append(stripped[2:].strip())
    return findings


def cites_a_source(finding: str, sources: list[str]) -> bool:
    return any(source in finding for source in sources)
