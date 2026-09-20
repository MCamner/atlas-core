"""Which claims in an output are traceable to something that was actually read.

The evaluator uses this to grade whether a finding is supported, rather than
whether it is well formatted. Nothing here interprets meaning: it matches
finding text against the source labels the adapters put in the observation
list. That is deliberately shallow — it can tell that a finding cites no
source at all, which is the failure mode worth catching, and it never claims
to have checked that a cited finding is *true*.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from .claim_check import ClaimCondition, build_condition
from .finding import EvidenceRef, Finding

#: Where an output puts the machine-readable half of its findings. A fenced
#: block with its own info string, so it cannot be confused with any other JSON
#: an answer happens to contain.
FINDINGS_FENCE = "atlas-findings"

_FINDINGS_BLOCK = re.compile(
    r"^```" + FINDINGS_FENCE + r"\s*\n(.*?)\n^```", re.DOTALL | re.MULTILINE
)

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


@dataclass(frozen=True)
class ParsedFindings:
    """The structured half of an output, and why it is missing if it is.

    Prose and structure are read separately and then matched, rather than one
    being derived from the other. A bullet can be written without a citation —
    that is the case worth catching — and deriving the structure from the prose
    would manufacture the very thing the check is supposed to demand.
    """

    #: Each finding with the condition it declared, if any. Paired rather than
    #: kept in two lists, so a condition can never drift onto another finding.
    entries: list[tuple[Finding, ClaimCondition | None]] = field(default_factory=list)
    #: Present but unreadable. Distinct from absent: one is a producer bug the
    #: next pass can fix, the other may mean the route simply claims nothing.
    malformed: str | None = None
    present: bool = False

    @property
    def findings(self) -> list[Finding]:
        return [finding for finding, _ in self.entries]

    def claims(self) -> list[str]:
        return [finding.claim for finding in self.findings]


def structured_findings(output: str) -> ParsedFindings:
    """Read the `atlas-findings` block, if the output carries one.

    A malformed block is reported, never skipped. Silently ignoring it would
    turn a producer's broken citation into "this route asserts nothing", which
    reads as clean rather than as the failure it is.
    """
    match = _FINDINGS_BLOCK.search(output)
    if match is None:
        return ParsedFindings()

    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError as error:
        return ParsedFindings(malformed=f"block is not valid JSON: {error}", present=True)

    if not isinstance(payload, list):
        return ParsedFindings(
            malformed=f"block must be a list of findings, got {type(payload).__name__}",
            present=True,
        )

    entries: list[tuple[Finding, ClaimCondition | None]] = []
    for index, item in enumerate(payload):
        try:
            entries.append((_build_finding(item), _build_condition(item)))
        except (TypeError, KeyError, ValueError) as error:
            return ParsedFindings(
                malformed=f"finding {index} is not usable: {error}", present=True
            )
    return ParsedFindings(entries=entries, present=True)


def _build_condition(item: object) -> ClaimCondition | None:
    """Read the finding's declared refutation condition, if it names one.

    A malformed declaration raises rather than being dropped: a producer that
    tried to say how it could be wrong and got the form wrong must not be
    graded as one that said nothing.
    """
    if not isinstance(item, dict):
        raise TypeError(f"expected an object, got {type(item).__name__}")
    return build_condition(item.get("claim_check"))


#: What a producer may supply, per schemas/atlas-findings-block.v1.json.
#: `finding_id`, `verdict` and `verification_method` are absent on purpose: they
#: are assigned by whatever checked the finding. A producer that sends one is
#: declaring its own success, so the block is refused rather than quietly
#: stripped — swallowing it would let a bad habit pass unremarked.
_PRODUCER_KEYS: frozenset[str] = frozenset(
    {
        "claim",
        "scope",
        "severity",
        "severity_rationale",
        "evidence",
        "claim_check",
        "limitations",
        "reproducible_command",
    }
)


def _build_finding(item: object) -> Finding:
    if not isinstance(item, dict):
        raise TypeError(f"expected an object, got {type(item).__name__}")
    undeclared = sorted(set(item) - _PRODUCER_KEYS)
    if undeclared:
        raise ValueError(
            f"undeclared field(s) {undeclared}: a producer supplies the claim and its "
            "evidence, never the verdict, the method or the id — those are assigned "
            "by whatever checked it"
        )
    references = item.get("evidence")
    if not isinstance(references, list):
        raise TypeError("evidence must be a list of citations")
    return Finding.create(
        claim=str(item["claim"]),
        scope=str(item["scope"]),
        severity=str(item.get("severity", "unknown")),
        severity_rationale=str(item.get("severity_rationale", "")),
        evidence=[_build_reference(reference) for reference in references],
        limitations=[str(limit) for limit in item.get("limitations") or []],
        reproducible_command=str(item.get("reproducible_command", "unknown")),
    )


def _build_reference(reference: object) -> EvidenceRef:
    if not isinstance(reference, dict):
        raise TypeError(f"expected a citation object, got {type(reference).__name__}")
    return EvidenceRef(
        source_id=str(reference["source_id"]),
        content_sha256=str(reference["content_sha256"]),
        line_start=int(reference["line_start"]),
        line_end=int(reference["line_end"]),
        quoted=str(reference["quoted"]),
    )
