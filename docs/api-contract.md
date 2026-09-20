# Atlas Loop API Contract

Atlas Core 1.x keeps its public Python types, JSON documents, stop semantics,
and adapter boundaries stable. Incompatible changes require a new major
version or a new schema identifier.

## Public Python API

Import supported types from the package root:

```python
from atlas_core import (
    AtlasController,
    AtlasEvaluation,
    AtlasPlan,
    AtlasRoute,
    AtlasRunState,
    EvidenceBase,
    ModelAdapter,
    ModelResult,
)
```

`AtlasController.run(..., json_mode=False)` returns the finalized text.
With `json_mode=True`, it returns an `atlas-run.v1` dictionary.

`run` takes two separate source channels, and they are not interchangeable:

| Parameter | What it is | How it is graded |
| --- | --- | --- |
| `observations: list[str]` | Prose context an adapter formatted. | Citation only: does a finding name a source that was read? |
| `evidence: EvidenceBase \| None` | A snapshot and the `Observation` objects taken against it. | Deterministic: is each citation still sound against the source? |

There is deliberately **no conversion** between them. Building an `Observation`
from a formatted string would require inventing a digest, a line range and a
snapshot, producing a source that claims to be verifiable while nothing behind
it was read. Callers that want the stricter gate must collect real
observations, with `atlas_core.snapshot.take_snapshot` and
`collect_observation`.

`max_iterations` must be a positive integer. The loop never executes more than
that number of iterations.

## JSON Schemas

The stable documents are:

- `schemas/atlas-run.v1.json`
- `schemas/atlas-route.v1.json`
- `schemas/atlas-evaluation.v1.json`
- `schemas/atlas-memory-candidate.v1.json`

These schemas are closed to undeclared top-level fields. New optional fields may
be added compatibly; removing fields, changing their meaning, or changing types
requires a new schema version.

`atlas-evaluation.v1` carries two independent verdicts, and adapters should not
collapse them:

| Field | Question it answers |
| --- | --- |
| `missing_sections` | Does the output have the shape the route promised? |
| `evidence_gaps` | Are the claims in it supported by something that was read? |

`unverified_claims` lists findings that are not supported — hypotheses, not
findings. `evidence_coverage` is the share of findings that are supported, or
`null` when the route has no evidence contract or the output asserts no
finding. `citation_checks` records, per finding, what the deterministic check
established. All are optional additions to the existing schema; a consumer
written against 1.0 that ignores them still reads a valid document.

### Which grading ran

A run without an evidence base is graded exactly as it was in 1.0: a finding
counts as covered when it **names** a source that was read. Nothing compares
the claim against that source's contents, so a factually wrong statement that
mentions `README.md` passes that gate. `citation_checks` is empty for such a
run, and `evidence_base` in the run document is `null`, so a reader can always
tell a checked run from an unchecked one.

A run with an evidence base is graded against `check_finding`. Every finding
under the route's finding headings must carry a machine-readable citation in an
```` ```atlas-findings ```` block, and that citation must survive: the
`source_id` must have been read this run, the claimed digest must match, the
observation's own excerpt must still match the lines it names, and the quote
must sit inside the range the observation recorded. A finding that fails any of
those cannot contribute to `passed`.

### Sound is still not verified

Surviving that check means the **pointer** holds, not that the source supports
the claim. `citation_checks[].verdict` is always `insufficient_evidence`;
`citations_are_sound` is what carries the difference. A false claim with a
correctly quoted citation therefore still passes the gate. Closing that is
semantic verification, which this repository does not perform yet — see
`ROADMAP.md` P0.2. `evidence_gaps` being empty means "every claim here is
eligible to be verified", never "this output is correct".

## Stop Semantics

Terminal runs expose both `status` and `stop_reason`:

| Status | Stop reason | Meaning |
| --- | --- | --- |
| `done` | `passed` | Evaluation passed the quality gate. |
| `done` | `no_actionable_retry` | Evaluation failed, but another pass cannot close a known gap. |
| `done` | `max_iterations` | A known gap remains and the iteration bound was reached. |
| `need_user_approval` | `approval_required` | The task appears to require mutation. |
| `failed` | `failed` | A model adapter raised, or returned a result that breaks the adapter contract. |

Adapters must use `stop_reason`; they must not infer completion semantics from
prose output. The text form of a run is rendered from the run document by
`render_run_text`, so it is a view of that document rather than a second source
of truth.

### CLI exit codes

`atlas run` maps the terminal state to an exit code, so a script can branch
without parsing output:

| Code | Meaning | Stop reasons |
| --- | --- | --- |
| 0 | The answer passed its quality gate. | `passed` |
| 1 | The run failed, or stopped for an unrecognised reason. | `failed` |
| 2 | The run finished without passing. | `no_actionable_retry`, `max_iterations` |
| 3 | A mutation needs explicit approval before anything runs. | `approval_required` |

Exit 2 is not an error. It means the loop stopped honestly rather than
claiming an answer it could not support — a `repo_review` with no observed
sources is the common case.

## Adapter Boundary

Model adapters receive task, route, plan, observations, and optional evaluation
feedback, and return `ModelResult`. Memory adapters expose `read` and `write`.
The core remains functional when neither is configured.

A model adapter that raises, or returns anything other than a `ModelResult`
with non-empty output, ends the run as `failed` / `failed`, with the stage and
exception type recorded under `metadata.failure`. It does **not** fall back to
the rule-based executor: reporting a deterministic template as though a model
had produced it would be a false success. The rule-based executor is the
default when no adapter is configured, which is a different situation.

**Timeouts are the adapter's responsibility.** `execute()` is a synchronous
call, and the core cannot cancel one in progress, so it does not pretend to
impose a deadline. An adapter talking to a network provider must set its own
timeout and raise on expiry; the core will then record it as a controlled
failure like any other.

`StubModelAdapter` is exported for tests and CI: it drives the model path
deterministically with no provider or API key, and records the calls it
received.

Observations are the evidence base. An adapter that wants its output to count
as a citable source must label it `<path>:` on its own line, as the filesystem,
GitHub and mqobsidian adapters do. Durable memory is excluded by design: it is
context, not current runtime truth, so it cannot support a claim about how a
repository looks now.

Adapters may add observations or produce output, but they do not change route,
evaluation, or stop semantics. Memory writes accept candidates; memory is not a
source of current runtime truth.

## Write Boundary

Atlas Core does not provide repository or service mutation tools. Write-like
tasks stop with `need_user_approval` and `approval_required`. An external
adapter capable of mutation must obtain explicit approval immediately before
performing that mutation; the core's keyword detection is advisory and does not
replace adapter-side authorization.
