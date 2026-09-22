"""Measuring a run against an answer key.

ROADMAP.md P1.1 box two. A loop that grades its own output needs something
outside itself to be graded against, or the only thing anyone can say about it
is that it agreed with itself.

## What a defect is here

A ground-truth defect is a **predicate the deterministic checker can settle**:
literal presence or absence over observed lines, on a named path. A defect that
cannot be written that way is not in the answer key, because a benchmark whose
key cannot be checked measures the reader's opinion of the output rather than
the output.

Matching is therefore exact. A finding counts against a defect when its typed
claim names the same path, kind and text — never by comparing prose, which
would let a generous reader score a vague sentence as a hit.

## What this measures, and what it does not

It measures the **gate**, not a finder. Atlas Core ships no live model, so the
findings a run contains are whatever its producer emitted. What the numbers
answer is: given these findings, does the loop establish the ones the source
supports, refuse the ones it contradicts, and refuse to dress up the rest?
Whether a model is any good at *noticing* the defects is P1.2, and this module
is the instrument that measurement will need.

## The metric that is easy to leave out

`overstates_completeness`. A review that asserts nothing passes — there is
nothing to settle, which is the right answer to "did your claims hold". It is
not the right answer to "is this repository sound", and those two read alike:
`passed`, every criterion met, a full score. A benchmark that only counted
findings would score an empty review as flawless. This one records it.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

SCHEMA = "atlas-measurement.v1"
GROUND_TRUTH_SCHEMA = "atlas-ground-truth.v1"


@dataclass(frozen=True)
class Defect:
    """One known defect, as a predicate rather than a description."""

    id: str
    path: str
    summary: str
    kind: str
    text: str

    def predicate(self) -> tuple[str, str, str]:
        """What a finding has to claim, exactly, to be counted against this."""
        return (self.path, self.kind, self.text)


@dataclass(frozen=True)
class GroundTruth:
    repo: str
    defects: list[Defect] = field(default_factory=list)

    @classmethod
    def load(cls, path: str | Path) -> GroundTruth:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
        if document.get("schema") != GROUND_TRUTH_SCHEMA:
            raise ValueError(
                f"expected {GROUND_TRUTH_SCHEMA}, got {document.get('schema')!r}"
            )
        return cls(
            repo=str(document["repo"]),
            defects=[
                Defect(
                    id=str(item["id"]),
                    path=str(item["path"]),
                    summary=str(item["summary"]),
                    kind=str(item["check"]["kind"]),
                    text=str(item["check"]["text"]),
                )
                for item in document.get("defects", [])
            ],
        )

    def by_predicate(self) -> dict[tuple[str, str, str], Defect]:
        return {defect.predicate(): defect for defect in self.defects}


@dataclass(frozen=True)
class Measurement:
    """What one run did, against what was actually there."""

    schema: str
    repo: str
    #: How many findings the output asserted at all.
    asserted: int
    #: Settled against observed lines, in the claim's favour.
    verified: int
    #: The source says otherwise. This is the sharpest kind of false positive:
    #: the run asserted something and its own evidence refuted it.
    refuted: int
    #: Neither. Free text, a broken citation, a source that moved.
    unestablished: int
    #: Ground-truth ids a verified finding established.
    found_defects: list[str]
    #: Ground-truth ids nothing in the run established.
    missed_defects: list[str]
    #: Claims established against the source that correspond to no known
    #: defect. True about the file and not a defect — noise, not a lie, and
    #: counted apart from `refuted` because the two need different fixes.
    verified_non_defects: int
    #: Of everything the run *established*, the share that is a known defect.
    #: None when it established nothing, rather than 0.0: a run that asserted
    #: nothing has no precision, and reporting one would invent a measurement.
    #:
    #: A share of the findings the run **established**: of those, how many hit
    #: a known defect. Not a share of the distinct defects — that is `recall`'s
    #: business, and counting distinct ids against a count of findings would
    #: report a run that stated one real defect twice as half wrong.
    precision: float | None
    #: Of everything the run asserted, the share it backed with evidence.
    evidence_backed_share: float | None
    #: Of the known defects, the share established.
    recall: float | None
    iterations: int
    stop_reason: str
    passed: bool
    cost: dict[str, Any]
    #: The run met its gate while asserting nothing. True is not a failure —
    #: it is the case a reader is most likely to misread, so it is named.
    overstates_completeness: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _typed_predicate(record: dict[str, Any]) -> tuple[str, str, str] | None:
    """The (path, kind, text) a finding claimed, if it made a typed claim.

    Read from `claim_check.checked`, which is what the checker actually
    settled — not from the prose, which may say anything.
    """
    claim_check = record.get("claim_check") or {}
    checked = claim_check.get("checked") or {}
    kind, path, text = checked.get("kind"), checked.get("path"), checked.get("text")
    if kind is None or path is None or text is None:
        return None
    return (str(path), str(kind), str(text))


def measure(run: dict[str, Any], truth: GroundTruth) -> Measurement:
    """Score one run document against an answer key.

    Reads the run document only. Nothing here re-reads a source or re-decides
    a verdict: the loop's verdicts are the thing being measured, and a
    benchmark that recomputed them would be marking its own homework twice.
    """
    evaluations = run.get("evaluations") or []
    latest = evaluations[-1] if evaluations else {}
    records = latest.get("citation_checks") or []
    unchecked = [str(claim) for claim in (latest.get("unverified_claims") or [])]

    verified = [r for r in records if r.get("verdict") == "verified"]
    refuted = [r for r in records if r.get("verdict") == "contradicted"]
    # Findings the checker saw but did not settle, plus claims that never
    # reached it at all. Both are assertions the run failed to establish.
    seen_claims = {str(r.get("claim", "")) for r in records}
    unestablished = len(records) - len(verified) - len(refuted) + len(
        [claim for claim in unchecked if claim not in seen_claims]
    )
    asserted = len(records) + len([c for c in unchecked if c not in seen_claims])

    known = truth.by_predicate()
    found: list[str] = []
    #: Verified findings that hit a known defect, **not** deduplicated. It is
    #: the numerator of precision, which is a share of what the run
    #: established, so it has to count the same thing the denominator counts.
    #: `found` is deduplicated because recall is a share of the *defects*, and
    #: a defect found twice is still one defect found. Mixing the two made a
    #: run that stated a real defect twice look half wrong.
    defect_hits = 0
    non_defects = 0
    for record in verified:
        predicate = _typed_predicate(record)
        defect = known.get(predicate) if predicate else None
        if defect is not None:
            defect_hits += 1
            if defect.id not in found:
                found.append(defect.id)
        else:
            non_defects += 1

    missed = [defect.id for defect in truth.defects if defect.id not in found]
    established = len(verified)
    passed = bool(latest.get("passed"))

    return Measurement(
        schema=SCHEMA,
        repo=truth.repo,
        asserted=asserted,
        verified=established,
        refuted=len(refuted),
        unestablished=unestablished,
        found_defects=found,
        missed_defects=missed,
        verified_non_defects=non_defects,
        precision=round(defect_hits / established, 2) if established else None,
        evidence_backed_share=round(established / asserted, 2) if asserted else None,
        recall=round(len(found) / len(truth.defects), 2) if truth.defects else None,
        iterations=int(run.get("iteration", 0)),
        stop_reason=str(run.get("stop_reason") or "unknown"),
        passed=passed,
        cost=dict((run.get("metadata") or {}).get("budget_usage") or {}),
        # Asserting nothing and meeting the gate. See the module docstring.
        overstates_completeness=passed and asserted == 0,
    )


__all__ = [
    "GROUND_TRUTH_SCHEMA",
    "SCHEMA",
    "Defect",
    "GroundTruth",
    "Measurement",
    "measure",
]
