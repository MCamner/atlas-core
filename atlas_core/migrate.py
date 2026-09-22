"""`atlas-run.v1` to `Run.v2`, without losing anything on the way.

A migration is a claim about two documents: that the second says everything the
first did. The claim is easy to make and easy to break, and the way it breaks is
quiet — a field nobody mapped, a default that reads like a measurement. So this
module is built around three rules, each of which has a test that fails when it
is broken rather than a comment saying it should not be.

**Nothing is dropped.** Every key in the source document is either mapped to a
v2 field or kept verbatim in `migration.unmapped`. Not its name — its value,
because a migration that records only *that* something was dropped has still
dropped it. The test is a set equation over the source's own keys, so a field
added to v1 later cannot slip through by being unknown to this code.

**Nothing is invented.** A v2 field the source could not have had is `null`, and
named in `migration.not_recorded`. Never `[]`, never `0`, never a plausible
string. `actions` is the sharp case: an empty list would state that the run
performed no actions, which is a claim, and a false one — v1 kept no action log
at all. `score_method` is the other: a document old enough to lack it is old
enough to hold the *weighted* score, so filling in today's method would assert
the one thing that cannot be known. It becomes `unknown`.

**Nothing is required to be complete.** A source missing a field its own schema
required is migrated anyway, with the absence recorded in `migration.missing`.
Refusing would leave the only copy in the old format; filling it in would be
worse. The one exception is `schema` itself: a document that does not say what
it is cannot be migrated, because every rule above is relative to a source
contract. That raises.

What this module does *not* do is change what the loop emits. `AtlasRunState`
still writes `atlas-run.v1`; moving the runtime onto v2 is a separate decision
with separate consequences for every consumer, and bundling it here would mean
the migration and the cutover could not be reviewed apart.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

from .contracts import RUN_V2_CONTRACTS
from .safety import requires_write_approval

SOURCE_SCHEMA = "atlas-run.v1"
TARGET_SCHEMA = "atlas-run.v2"
EVALUATION_SCHEMA = "atlas-evaluation.v2"
APPROVAL_SCHEMA = "atlas-approval.v1"

#: Everything `atlas-run.v1` requires. Held here rather than read from the
#: schema file at runtime: `schemas/` is repository documentation and is not
#: packaged, so a runtime read would work in the repository and fail in an
#: installed wheel. A test binds this list to the file.
V1_REQUIRED: tuple[str, ...] = (
    "schema", "task", "run_id", "created_at", "status", "stop_reason",
    "iteration", "max_iterations", "route", "plan", "observations",
    "outputs", "evaluations", "memory_candidates", "metadata",
)

#: Everything `atlas-run.v2` requires. Held here for the same reason as
#: `V1_REQUIRED`, and used for a different question: `V1_REQUIRED` asks what the
#: source should have had, this asks whether the result is a valid v2 document.
#: They are not the same question, and a migration that answered only the first
#: reported a result as complete while a required field was absent from it.
V2_REQUIRED: tuple[str, ...] = (
    "schema", "contracts", "task", "run_id", "created_at", "status",
    "stop_reason", "iteration", "max_iterations", "route", "plan",
    "observations", "outputs", "evaluations", "actions", "approvals",
    "memory_candidates", "metadata",
)

#: Fields that move across under the same name and meaning. Listed rather than
#: copied wholesale so that a v1 field this code has never seen ends up in
#: `unmapped` and is noticed, instead of being carried silently into a v2
#: document whose schema forbids it.
CARRIED: tuple[str, ...] = (
    "run_id", "task", "created_at", "status", "stop_reason", "stop_class",
    "state_machine", "iteration", "max_iterations", "route", "plan",
    "observations", "evidence_manifest", "outputs", "memory_candidates",
    "metadata",
)

#: v2 fields no `atlas-run.v1` document could have carried. Null in the output
#: and named in the report, which is the whole of the no-invented-default rule
#: as it applies at the document level.
NOT_RECORDED_IN_V1: tuple[str, ...] = ("actions",)


@dataclass(frozen=True)
class MigrationReport:
    """What the migration could carry, and what it could not.

    Four lists rather than a boolean, because "lossless" is not one question.
    A field kept verbatim under another name, a field the source never had, and
    a field the source should have had and did not are three different facts
    about the result, and a reader deciding whether to trust it needs all three.
    """

    #: Source keys that reached a v2 field of the same meaning.
    mapped: tuple[str, ...] = ()
    #: Source keys v2 has no place for, kept verbatim under `migration.unmapped`.
    unmapped: Mapping[str, Any] = field(default_factory=dict)
    #: Keys the source schema required and the source did not have.
    missing: tuple[str, ...] = ()
    #: Fields `Run.v2` requires that the result does not carry. A different
    #: question from `missing`: a source can hold a key whose *value* is not
    #: something the target field can contain, and then the key was neither
    #: absent from the source nor present in the result. That gap is how a
    #: migration once reported itself complete while replacing a value with a
    #: claim of its own.
    unfilled: tuple[str, ...] = ()
    #: v2 fields the source version could not have had.
    not_recorded: tuple[str, ...] = ()
    #: Contradictions in the source that were preserved rather than corrected.
    #: A migration that silently repairs its input is a migration whose output
    #: cannot be compared with it.
    inconsistent: tuple[str, ...] = ()

    @property
    def is_complete(self) -> bool:
        """Whether the result satisfies everything `Run.v2` requires.

        Separate from `is_lossless`, because they fail for opposite reasons. A
        lossy migration carried *more* than v2 has room for; an incomplete one
        carried less than v2 demands, because the source did not have it.

        The result of an incomplete migration is a document that does not
        validate against its own schema, and that is the honest outcome: the
        alternative is a default indistinguishable from a value the run
        produced. A caller that needs a valid document checks this and decides;
        nothing here decides for it, and nothing pretends.

        Read off the result, not off the source. Answering from `missing` alone
        said "complete" for a source that carried `evaluations` with a value no
        v2 array could hold — the key was present, so it was not missing, and
        the result had no `evaluations` at all.
        """
        return not self.unfilled

    @property
    def is_lossless(self) -> bool:
        """Whether every source key reached a v2 field of the same meaning.

        `unmapped` makes it false. That is deliberate and it is not a failure:
        the values are still in the document, and saying "lossless" about a
        result that had to park something under another name would be the exact
        overstatement this module exists to prevent.
        """
        return not self.unmapped

    def to_dict(self, source_schema: str, migrated_at: str) -> dict[str, Any]:
        return {
            "from": source_schema,
            "to": TARGET_SCHEMA,
            "migrated_at": migrated_at,
            "unmapped": dict(self.unmapped),
            "missing": list(self.missing),
            "unfilled": list(self.unfilled),
            "not_recorded": list(self.not_recorded),
        }


class UnknownSourceSchema(ValueError):
    """The document does not say which contract it is.

    Every rule in this module is relative to a source contract — which fields
    are required, which are known, which could not exist. Guessing the source
    from its shape would make all three guesses.
    """


def _stable_id(*parts: object) -> str:
    material = json.dumps([str(part) for part in parts], sort_keys=True)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def migrate_run(document: Mapping[str, Any]) -> tuple[dict[str, Any], MigrationReport]:
    """Return an `atlas-run.v2` document and the report of what it cost.

    The report is returned rather than only embedded, so a caller can refuse a
    migration it does not like without having to parse its own output.
    """
    declared = document.get("schema")
    if declared == TARGET_SCHEMA:
        raise UnknownSourceSchema(
            f"document already declares {TARGET_SCHEMA}; migrating it again "
            "would record a migration that did not happen"
        )
    if declared != SOURCE_SCHEMA:
        raise UnknownSourceSchema(
            f"expected {SOURCE_SCHEMA!r}, got {declared!r}; a document that does "
            "not name its contract cannot be migrated, because which fields are "
            "required, known and impossible are all relative to it"
        )

    missing = tuple(key for key in V1_REQUIRED if key not in document)
    run_id = document.get("run_id", "")

    target: dict[str, Any] = {"schema": TARGET_SCHEMA, "contracts": dict(RUN_V2_CONTRACTS)}
    mapped = ["schema"]
    for key in CARRIED:
        if key in document:
            target[key] = document[key]
            mapped.append(key)

    evaluations_in = document.get("evaluations")
    inconsistent: list[str] = []
    if isinstance(evaluations_in, list):
        mapped.append("evaluations")
        # One evaluation per pass, appended in order, so index i is iteration
        # i+1. A run that stopped before grading has fewer evaluations than
        # iterations, which is normal; more evaluations than iterations is not
        # possible and is recorded rather than smoothed over.
        run_iterations = document.get("iteration")
        if isinstance(run_iterations, int) and len(evaluations_in) > run_iterations:
            inconsistent.append("evaluations longer than iteration count")
        target["evaluations"] = [
            _migrate_evaluation(item, run_id, index + 1)
            for index, item in enumerate(evaluations_in)
        ]
        target["approvals"] = _approvals_from(evaluations_in, run_id, document)
    else:
        # A value no v2 array can hold. It is *not* normalised to `[]`: that
        # would drop what the source said and replace it with a claim of this
        # module's own — that the run was graded zero times. It falls through to
        # `unmapped` like any other value v2 has no place for, and the target
        # simply has no `evaluations`, which `unfilled` then reports.
        #
        # This was a real hole, found in review: `unmapped` used to exclude the
        # key unconditionally, so the value vanished, `[]` took its place, and
        # the migration called itself both lossless and complete.
        #
        # No evaluations to derive from. Null rather than `[]`: an empty list
        # would say nobody needed approval, and nobody asked.
        target["approvals"] = None

    for key in NOT_RECORDED_IN_V1:
        target[key] = None

    unmapped = {
        key: value for key, value in document.items() if key not in mapped
    }
    unfilled = tuple(key for key in V2_REQUIRED if key not in target)

    report = MigrationReport(
        mapped=tuple(mapped),
        unmapped=unmapped,
        missing=missing,
        unfilled=unfilled,
        not_recorded=NOT_RECORDED_IN_V1,
        inconsistent=tuple(inconsistent),
    )
    target["migration"] = report.to_dict(
        str(declared), datetime.now(timezone.utc).isoformat()
    )
    return target, report


def _migrate_evaluation(
    item: Mapping[str, Any], run_id: str, iteration: int
) -> dict[str, Any]:
    """One `atlas-evaluation.v1` into a v2 record.

    Everything the source had is carried under its own name. What is added is
    identity, which v1 had none of — an evaluation was its position in a list,
    so two documents could not be said to hold the same one.
    """
    record = dict(item)
    record["schema"] = EVALUATION_SCHEMA
    record["run_id"] = run_id
    record["iteration"] = iteration
    record["evaluation_id"] = _stable_id(run_id, iteration)
    # Required in v2 and optional in v1. `unknown` rather than today's method:
    # a document without the field may hold the *weighted* score, and writing
    # `criteria_met_share` would assert precisely what cannot be known.
    if not record.get("score_method"):
        record["score_method"] = "unknown"
    return record


def _approvals_from(
    evaluations: list[Any], run_id: str, document: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """An `atlas-approval.v1` per iteration that needed a person.

    Derived, not invented: `requires_user_approval` is information v1 genuinely
    carried, and this restates it as its own record. What v1 did *not* carry is
    why — so `reason` is `not_recorded` unless the task itself still answers it,
    and the grant fields are null because no grant has ever existed.
    """
    approvals: list[dict[str, Any]] = []
    task = document.get("task")
    for index, item in enumerate(evaluations):
        if not isinstance(item, Mapping) or not item.get("requires_user_approval"):
            continue
        iteration = index + 1
        # The one honest reason available: the rule that sets the flag reads the
        # task, and the task is in the document. Where it does not fire, the
        # flag came from somewhere this migration cannot see, and says so.
        derived = (
            "task_matches_write_keyword"
            if isinstance(task, str) and requires_write_approval(task)
            else "not_recorded"
        )
        approvals.append(
            {
                "schema": APPROVAL_SCHEMA,
                "approval_id": _stable_id(run_id, iteration, "approval"),
                "run_id": run_id,
                "iteration": iteration,
                "required": True,
                "reason": derived,
                # Null, not False. Nobody refused; nobody was asked. There is no
                # grant mechanism in this version, and there is no such thing as
                # an approval that binds to nothing.
                "granted": None,
                "granted_by": None,
                "granted_at": None,
                "binds_to": None,
            }
        )
    return approvals


def approval_is_well_formed(record: Mapping[str, Any]) -> bool:
    """Whether a grant says what it is a grant of.

    The one rule in `atlas-approval.v1` that a structural check would miss, and
    the one that matters: `granted: true` without `binds_to` is an approval of
    everything, forever. Enforced here so the contract is not merely described.
    """
    if record.get("granted") is not True:
        return True
    binds = record.get("binds_to")
    return isinstance(binds, dict) and bool(binds.get("kind")) and bool(binds.get("sha256"))


__all__ = [
    "APPROVAL_SCHEMA",
    "CARRIED",
    "EVALUATION_SCHEMA",
    "MigrationReport",
    "NOT_RECORDED_IN_V1",
    "SOURCE_SCHEMA",
    "TARGET_SCHEMA",
    "UnknownSourceSchema",
    "V1_REQUIRED",
    "V2_REQUIRED",
    "approval_is_well_formed",
    "migrate_run",
]
