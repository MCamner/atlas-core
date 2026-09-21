"""The verifiable sources a run holds, kept apart from its prose context.

ROADMAP.md P0.2, the bridge between P0.1 and evaluation. Before this module a
run carried `list[str]` — blobs an adapter had formatted, from which
`evidence.observed_sources` recovered a filename. That is context. It is not
evidence: nothing in it can be re-read, re-hashed or shown to still describe
its source.

This module adds the second channel and **keeps the two apart on purpose**:

- `AtlasRunState.observations` stays `list[str]` and keeps its old meaning. It
  is what the executor renders and what the citation-only grading reads.
- `AtlasRunState.evidence_base` is `Observation` objects and the `Snapshot`
  they were taken against, which `check_finding` can verify.

A run without an evidence base is graded exactly as it was, and the evaluator
says so in as many words rather than leaving a reader to assume the stricter
gate ran. There is deliberately **no** conversion from one to the other. A
function that turned a formatted string into an `Observation` would have to
invent a digest, a line range and a snapshot, and the result would be a source
that claims to be verifiable while nothing behind it was ever read — the exact
fabrication P0.1 exists to prevent. Callers that want the strict gate must
collect real observations.

## Raw stays local

The base holds raw excerpts and the absolute path the run read from. None of
that may reach a caller: `to_manifest()` is the only export, and it goes
through `integrity.redacted_manifest`, which masks credential shapes, home
directories and email addresses across the whole document and does not emit
`snapshot.root` at all. Redaction cannot help with an absolute path outside a
home directory — a temporary directory under `/private/var` matches no
pattern — so the root is dropped rather than masked.

`AtlasRunState.to_dict` therefore exports `evidence_manifest`, never the base
itself. The manifest's `verification` is `unknown` and `is_evidence` is false
by design: exporting is not verifying, and doing disk IO inside serialisation
would make a run document depend on when it was rendered. What *was* verified
is in each evaluation's `citation_checks`.

## What this does not do

It holds sources; it does not decide anything. Whether a finding's citations
survive is `finding.check_finding`, and whether an intact citation *supports*
the claim is P0.2b and is not answered anywhere in this repository yet.

It also does not clean up the rest of the run document. `AtlasRunState.
observations` — the prose channel — is still exported verbatim, as it has been
since 1.0. An adapter that puts file contents there still exports them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .finding import SourceReader
from .integrity import redacted_manifest
from .observation import Observation
from .snapshot import Snapshot


@dataclass(frozen=True)
class EvidenceBase:
    """One snapshot, and the observations taken against it.

    Validated in `__post_init__` rather than in a factory, so
    `dataclasses.replace` cannot produce a base whose observations belong to a
    state nobody took.
    """

    snapshot: Snapshot
    observations: list[Observation] = field(default_factory=list)
    #: How non-local sources are re-read. Local files always have a reader;
    #: anything else needs one from the host, because Atlas Core makes no
    #: network calls. A source with no reader is refused rather than guessed
    #: at — see `finding.resolve_readers`, which will not let this replace the
    #: local-file reader.
    readers: dict[str, SourceReader] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for observation in self.observations:
            if observation.snapshot_id != self.snapshot.snapshot_id:
                raise ValueError(
                    f"observation {observation.source_id} was taken against snapshot "
                    f"{observation.snapshot_id}, not {self.snapshot.snapshot_id}. A run "
                    "that mixes states cannot say which bytes backed a claim."
                )
        seen: set[str] = set()
        for observation in self.observations:
            if observation.source_id in seen:
                raise ValueError(
                    f"duplicate source_id {observation.source_id}: a citation would "
                    "not say which observation it means"
                )
            seen.add(observation.source_id)

    @property
    def root(self) -> Path:
        """Where verification re-reads from. The snapshot's root, not a caller's."""
        return Path(self.snapshot.root)

    def source_ids(self) -> list[str]:
        return [observation.source_id for observation in self.observations]

    def paths(self) -> list[str]:
        return [observation.path for observation in self.observations]

    def is_empty(self) -> bool:
        return not self.observations

    def can_reread(self, observation: Observation) -> bool:
        """Whether this run can establish that a source still holds."""
        return observation.source_type == "local_file" or observation.source_type in self.readers

    def with_observations(self, observations: list[Observation]) -> EvidenceBase:
        """A base holding `observations` instead, on the same snapshot.

        Returns a new base rather than mutating this one: an evidence base that
        could be edited after a claim was graded against it would make the
        grade unreadable. Validation runs again in `__post_init__`, so a
        replacement set that mixes snapshots or repeats a source is refused
        here exactly as an original one would be.

        Readers are carried over. They are how a non-local source is re-read,
        and a re-read set that lost them would silently become uncheckable.
        """
        return EvidenceBase(
            snapshot=self.snapshot,
            observations=list(observations),
            readers=dict(self.readers),
        )

    def to_manifest(self) -> dict[str, Any]:
        """The only export. Raw excerpts and the absolute root stay behind.

        See the module docstring for why the root is dropped rather than
        masked, and why this states no verification of its own.
        """
        return redacted_manifest(self.snapshot, self.observations)


__all__ = ["EvidenceBase"]
