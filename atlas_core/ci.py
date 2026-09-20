"""P0.2, box four: a CI result as a source that can go stale.

ROADMAP.md P0.2 asks for `stale CI` among the cases that must not pass. Until
now `ci` existed as a `SourceType` and nothing produced one, so a finding
citing CI was refused as `unsupported_source_type`. That is the right outcome
for the wrong reason, and a review said so plainly: refusing a source because
nobody can fetch it is not the same as testing what happens when a fetched one
goes out of date.

## What a CI observation records

A CI result is not a file. What identifies it is the run — provider, workflow,
run id, the ref and commit it ran against, its conclusion and when it finished.
`collect_ci_observation` canonicalises exactly those fields and hashes them, so
the digest changes when the *result* changes, not when an unrelated field of
some API response is reordered.

`path` is `ci://<provider>/<workflow>@<ref>`, which is an identifier and not a
filesystem location. Nothing reads it off disk; `read_within` refuses absolute
paths and this never reaches it, because a `ci` observation is re-read through
its adapter instead.

## Why it goes stale, and why that matters

A CI conclusion is the most perishable thing a review can cite. A run that was
green when it was read can be red a minute later, on the same commit, because
someone re-ran it — and a finding resting on "CI is green" is then false while
its citation still looks perfect. Re-fetching and comparing the digest is what
catches that, and `stale_source` is what it earns.

## The adapter boundary

Atlas Core makes no network calls. `CIAdapter` is the seam: a host supplies
something that can fetch a run, and this module turns it into provenance. That
keeps the core dependency-free and testable, and it keeps the fabrication rule
intact — no adapter means no CI observation, never an invented one.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from .observation import UNKNOWN, Observation
from .snapshot import Snapshot, sha256_text

#: Conclusions a provider may report. `unknown` is kept available for the same
#: reason it is everywhere else: a result nobody could establish must not be
#: recorded as a green one.
CONCLUSIONS: tuple[str, ...] = (
    "success",
    "failure",
    "cancelled",
    "timed_out",
    "in_progress",
    UNKNOWN,
)


@dataclass(frozen=True)
class CIRun:
    """One CI run, as far as a provider could establish it.

    Frozen and validated, so a caller cannot assemble a green result out of
    defaults it never fetched.
    """

    provider: str
    workflow: str
    run_id: str
    ref: str
    commit: str
    conclusion: str
    completed_at: str = UNKNOWN
    url: str = UNKNOWN

    def __post_init__(self) -> None:
        for name in ("provider", "workflow", "run_id", "ref", "commit"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string, got {value!r}")
        if self.conclusion not in CONCLUSIONS:
            raise ValueError(
                f"conclusion must be one of {CONCLUSIONS}, got {self.conclusion!r}"
            )

    def is_green(self) -> bool:
        """Only `success` counts. `unknown` and `in_progress` are not green."""
        return self.conclusion == "success"

    def identity(self) -> str:
        return f"ci://{self.provider}/{self.workflow}@{self.ref}"

    def canonical(self) -> str:
        """The bytes the digest is taken over.

        Sorted keys and a fixed separator, so re-fetching an unchanged run
        yields the same digest and a changed conclusion yields a different one.
        A provider reordering its JSON must not read as drift.
        """
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))


class CIAdapter(Protocol):
    """How a host fetches a CI run. Atlas Core makes no network calls itself."""

    def fetch(self, ref: str) -> CIRun: ...


class StubCIAdapter:
    """A deterministic stand-in, shipped so the CI path has one reference.

    `set_run` is what makes staleness testable: a run can change between being
    observed and being verified, which is exactly what happens when someone
    re-runs a workflow.
    """

    def __init__(self, run: CIRun):
        self._run = run
        self.fetches = 0

    def set_run(self, run: CIRun) -> None:
        self._run = run

    def fetch(self, ref: str) -> CIRun:
        self.fetches += 1
        return self._run


def collect_ci_observation(
    snapshot: Snapshot, adapter: CIAdapter, ref: str, *, confidentiality: str = UNKNOWN
) -> Observation:
    """Fetch a CI run and record it with its provenance.

    The excerpt is the canonical payload, so what a reviewer reads is what the
    digest covers. `line_start`/`line_end` are 1..1: the payload is one record,
    and pretending it has a line range would invite citations into a structure
    that does not exist.
    """
    run = adapter.fetch(ref)
    payload = run.canonical()
    return Observation.create(
        source_type="ci",
        path=run.identity(),
        collected_at=datetime.now(timezone.utc).isoformat(),
        content_sha256=sha256_text(payload),
        excerpt=payload,
        line_start=1,
        line_end=1,
        snapshot_id=snapshot.snapshot_id,
        commit=run.commit,
        ref=run.ref,
        worktree_state=snapshot.worktree_state,
        confidentiality=confidentiality,
    )


class CIReader:
    """Re-reads a `ci` observation by asking the provider again.

    This is the whole point of the type: a CI conclusion is perishable, so
    "still true" is a question only the provider can answer. A cached copy
    would make every citation permanently fresh, which is the failure the
    roadmap names.
    """

    source_type = "ci"

    def __init__(self, adapter: CIAdapter):
        self._adapter = adapter

    def read(self, observation: Observation) -> str:
        return self._adapter.fetch(observation.ref).canonical()


def ci_readers(adapter: CIAdapter) -> dict[str, Any]:
    """The reader mapping to hand an `EvidenceBase` that holds CI sources."""
    return {"ci": CIReader(adapter)}


__all__ = [
    "CONCLUSIONS",
    "CIAdapter",
    "CIReader",
    "CIRun",
    "StubCIAdapter",
    "ci_readers",
    "collect_ci_observation",
]
