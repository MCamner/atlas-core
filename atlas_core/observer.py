"""Reading again, mid-run, without loosening what evidence means.

ROADMAP.md P1.1. Until now a run's evidence was fixed before it started: the
caller collected observations, handed them over, and whatever the loop found
missing it could only ask a producer to re-word. A gap that needed a *source*
had nowhere to go, so the run stopped `blocked` and a human went and looked.

This module is the other half. When an evaluation's next action is
`observe_again`, the loop asks the host to read — and everything that makes an
observation evidence has to survive that. Four rules, and they are the whole
module:

1. **One snapshot per run.** An observation that arrives bound to a different
   snapshot is refused, not adopted. A run that mixed two states could not say
   which bytes backed a claim, which is exactly what `EvidenceBase` has
   refused since it existed; asking the host for more evidence must not become
   the way around it.
2. **A changed source is not swapped in silently.** Re-reading a file that has
   changed yields the same `source_id` carrying different bytes — that is the
   design. What must not happen is the old observation quietly vanishing, so a
   replacement is recorded as a supersession with both digests. The lines an
   earlier claim rested on stay in that iteration's `citation_checks`, and a
   new finding that cites the old digest fails `digest_mismatch` rather than
   being silently re-pointed at content nobody compared it against.
3. **Nothing new is not a retry.** A round that returns nothing, or returns
   the same bytes again, has not moved the run. The loop stops and says so
   rather than spending an iteration on evidence it has already graded.
4. **Fail closed.** A host that raises, times out, exceeds the budget or
   returns something that does not bind to the run's snapshot ends the run.
   None of those may turn into a finding, and none of them may read as a
   verdict about an answer.

The host does the reading. Atlas Core makes no network calls and does not
choose what to open; it says which sources it could not stand behind and what
it is missing. Whether that is a local file, a GitHub blob or a CI run is the
host's business, and `Observation.v1` is the only shape the answer may take.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from .budget import RunBudget
from .observation import Observation
from .snapshot import Snapshot


class ObservationRefused(Exception):
    """A returned observation does not belong to this run.

    Raised rather than dropped. Ignoring one and carrying on with the rest
    would let a host widen a run's evidence by accident, and the run would
    report a grade over a set nobody agreed to.
    """


@dataclass(frozen=True)
class ObservationRequest:
    """What the run needs read again, and why.

    Carries the snapshot rather than only its id: a host that has to re-read
    needs the state to read *from*, and deriving it from a bare id would mean
    guessing. `paths` and `source_ids` describe the same sources twice on
    purpose — a host keyed by path and one keyed by id both get what they use.
    """

    snapshot: Snapshot
    #: Sources the run could not stand behind, by id.
    source_ids: list[str]
    #: The same sources by path, in the same order.
    paths: list[str]
    #: The status codes that made them unusable — `stale_source`, `missing`,
    #: and the rest of `EvidenceStatus`. A host may use them to decide how to
    #: read; it is not required to.
    blocked_by: list[str]
    #: The claims that rested on them, so a host can tell what the re-read is
    #: for rather than only that one is wanted.
    claims: list[str] = field(default_factory=list)
    #: Glob patterns the review plan asked for and nothing has answered yet.
    #: A host resolves these against the snapshot; `paths` is what the run has
    #: already read. On a first read `paths` is empty and this is the request.
    patterns: list[str] = field(default_factory=list)
    #: The question the read is in service of, so a host that can choose has
    #: something to choose by.
    question: str = ""
    iteration: int = 0


class Observer(Protocol):
    """How a host reads again, on the run's behalf.

    Read-only by contract. The loop calls this when it cannot stand behind a
    source, and it has no way to express a mutation — there is no write
    capability in P0 or P1, and adding one here would put it exactly where
    nothing is watching.

    The loop hands over the run's own `RunBudget`, the same object a model
    adapter receives. It is a handle to this run, not part of what was asked,
    which is why it travels beside the request instead of inside it: the
    request is what the event log digests. An implementation reserves a tool
    call per read and checks the budget between reads, so a read that no quota
    or deadline covers cannot happen through this door. The loop also checks
    before and after the call; it cannot preempt a synchronous host, and this
    module does not pretend otherwise. See `docs/safety-model.md`.
    """

    def observe(
        self, request: ObservationRequest, *, budget: RunBudget
    ) -> list[Observation]: ...


@dataclass(frozen=True)
class Supersession:
    """One source that came back carrying different bytes.

    Both digests, so a reader can tell which version a claim was graded
    against. This is what keeps rule 2 honest: the replacement happened and
    the record says so.
    """

    source_id: str
    path: str
    previous_sha256: str
    new_sha256: str


@dataclass(frozen=True)
class ObservationRound:
    """What one round of reading produced.

    `has_new_material` is the question the loop actually asks. A round that
    returned observations is not the same as a round that changed anything:
    a host can re-read a file that has not moved, and re-grading identical
    evidence is the retry this phase exists to refuse.
    """

    added: list[Observation]
    superseded: list[Supersession]
    unchanged: list[str]
    requested: int

    @property
    def has_new_material(self) -> bool:
        return bool(self.added or self.superseded)

    def to_dict(self) -> dict[str, object]:
        return {
            "requested": self.requested,
            "added": [
                {"source_id": o.source_id, "path": o.path, "sha256": o.content_sha256}
                for o in self.added
            ],
            "superseded": [
                {
                    "source_id": s.source_id,
                    "path": s.path,
                    "previous_sha256": s.previous_sha256,
                    "new_sha256": s.new_sha256,
                }
                for s in self.superseded
            ],
            "unchanged": list(self.unchanged),
        }


def merge_observations(
    snapshot: Snapshot,
    existing: list[Observation],
    incoming: list[Observation],
) -> tuple[list[Observation], ObservationRound]:
    """Fold a host's answer into what the run already holds.

    Refuses anything that is not an `Observation` bound to this run's snapshot,
    and refuses a duplicate inside one answer — two observations of the same
    source in one round cannot both be the current one, and picking either
    would be arbitrary.

    Returns the new observation list and the record of what changed. The list
    is a copy: the caller's evidence base is frozen, and rebuilding it is the
    caller's decision rather than a side effect of asking what arrived.
    """
    by_id = {observation.source_id: observation for observation in existing}
    merged = list(existing)
    added: list[Observation] = []
    superseded: list[Supersession] = []
    unchanged: list[str] = []
    seen: set[str] = set()

    for item in incoming:
        if not isinstance(item, Observation):
            raise ObservationRefused(
                f"an observer returns Observation.v1, got {type(item).__name__}"
            )
        if item.snapshot_id != snapshot.snapshot_id:
            raise ObservationRefused(
                f"observation {item.source_id} is bound to snapshot "
                f"{item.snapshot_id}, not {snapshot.snapshot_id}. A run that mixes "
                "states cannot say which bytes backed a claim."
            )
        if item.source_id in seen:
            raise ObservationRefused(
                f"{item.source_id} appears twice in one round; both cannot be the "
                "current reading of that source"
            )
        seen.add(item.source_id)

        previous = by_id.get(item.source_id)
        if previous is None:
            merged.append(item)
            added.append(item)
            continue
        if previous.content_sha256 == item.content_sha256:
            unchanged.append(item.source_id)
            continue
        superseded.append(
            Supersession(
                source_id=item.source_id,
                path=item.path,
                previous_sha256=previous.content_sha256,
                new_sha256=item.content_sha256,
            )
        )
        merged[merged.index(previous)] = item

    return merged, ObservationRound(
        added=added,
        superseded=superseded,
        unchanged=unchanged,
        requested=len(incoming),
    )


def request_from(
    snapshot: Snapshot,
    observations: list[Observation],
    blocked_by: list[str],
    claims: list[str],
    iteration: int,
    patterns: list[str] | None = None,
    question: str = "",
) -> ObservationRequest:
    """Build the request from what the run could not stand behind.

    Every source is named, not only the ones a finding cited. The drift gate
    stops a run when *any* observation stops verifying, so a host that re-read
    only the cited ones would hand back a set that still fails the same gate.
    """
    return ObservationRequest(
        snapshot=snapshot,
        source_ids=[observation.source_id for observation in observations],
        paths=[observation.path for observation in observations],
        blocked_by=list(blocked_by),
        claims=list(claims),
        patterns=list(patterns or []),
        question=question,
        iteration=iteration,
    )


__all__ = [
    "ObservationRefused",
    "ObservationRequest",
    "ObservationRound",
    "Observer",
    "Supersession",
    "merge_observations",
    "request_from",
]
