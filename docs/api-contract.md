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
    ModelAdapter,
    ModelResult,
)
```

`AtlasController.run(..., json_mode=False)` returns the finalized text.
With `json_mode=True`, it returns an `atlas-run.v1` dictionary.

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

`unverified_claims` lists findings that cite no observed source — hypotheses,
not findings. `evidence_coverage` is the share of findings that do name one, or
`null` when the route has no evidence contract or the output asserts no finding.
All three are optional additions to the existing schema; a consumer written
against 1.0 that ignores them still reads a valid document.

The check is **citation, not verification**. A finding counts as covered when it
names a source that was read. Nothing compares the claim against that source's
contents, so a factually wrong statement that mentions `README.md` still passes
the gate. `evidence_gaps` being empty means "this output is grounded in
something it read", not "this output is correct". Verifying the claim itself
needs a model adapter and is not part of this contract.

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
