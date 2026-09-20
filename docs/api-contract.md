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

The run document exports `evidence_manifest`, a sanitised
`atlas-observation-manifest.v1`, and never the evidence base itself. The base
holds unmasked excerpts and the absolute path the run read from; the root is
dropped rather than masked, because redaction recognises home directories and
credential shapes, not an arbitrary absolute path. The manifest's
`verification` is `unknown` and `is_evidence` is false by design — exporting is
not verifying, and disk IO inside serialisation would make a run document
depend on when it was rendered. What was verified is in `citation_checks`.

This does **not** make the whole document safe. `observations`, the prose
channel, is still exported verbatim as it has been since 1.0, so an adapter
that puts file contents there still exports them.

There is deliberately **no conversion** between the two channels. Building an `Observation`
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

### The claim check

A sound citation is not enough for `repo_review`. A finding earns a verdict of
`verified` or `contradicted` only by stating a **typed claim**, where the claim
*is* the predicate:

```json
{"kind": "source_contains_literal", "source_id": "...", "text": "pip install"}
```

The finding's `claim` string must equal the sentence derived from that object —
`README.md lines 1-5 contain "pip install"` — so the sentence a reader sees
cannot say more than what was tested. The derived sentence names the line
range, because claims are settled over the lines the observation recorded, not
the whole file. `collect_observation` keeps a bounded excerpt, and text nobody
observed must not decide a verdict.

Free text keeps `insufficient_evidence` and cannot reach `PASS`. A producer may
still declare a free-standing `claim_check`, which yields `condition_supported`
or `condition_refuted` — settling the *test*, not the claim. Nothing checks
that such a test is a fair test of a sentence, so neither result is decisive.
A finding declares a `typed_claim` or a `claim_check`, never both.

`schemas/atlas-findings-block.v1.json` is the producer's input contract, and it
has no `verdict`, `verification_method` or `finding_id` — those are assigned by
whatever checked the finding. A block that supplies one is refused, not
stripped.

Only a finding whose citations are sound reaches this step: a refutation
resting on a source the finding cannot point at would be an accusation about
the wrong file. A source that has moved settles nothing in either direction.

### What a passing run does and does not mean

`evidence_gaps` being empty means every finding was stated in a form this code
can settle, and settled in its favour, against lines that were actually read.
It does not mean the review is complete or insightful: a claim that cannot be
expressed as literal presence or absence over observed lines cannot be verified
here at all, and stays `insufficient_evidence`. That is the correct answer and
also the limit of what this phase reaches.

Text matching is literal. A producer-supplied regular expression is untrusted
input that can hang the checker; a substring search cannot.

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
