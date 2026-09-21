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

### What it takes to be done

Each route declares its **exit criteria**: named requirements, all of which
must be met. `met_criteria` and `unmet_criteria` say which, and `passed` is
exactly `unmet_criteria == [] and not requires_user_approval`.

`quality_score` is the share met, rounded to two places. It **reports**;
nothing compares it against a threshold. Until P1.1 it was the gate: a weighted
sum over output length and headings, times an evidence factor, against 0.78 —
arithmetic that never said what the route owed, and under which an answer could
pass with a section the route had declared still missing. `PASS_THRESHOLD`,
`SECTION_WEIGHTS` and the coverage factor are gone with it.

`repo_review` declares `sources_documented`, `findings_are_checkable`,
`citations_hold`, `claims_are_settled`, `recommendation`, `next_step` and
`confidence`. A route that checks nothing against a source declares
`substance` instead of the evidence criteria — length remains a proxy where
there is nothing better, and it is now named as one rather than folded into a
sum. A route that does check its claims does not need it: a short review whose
findings were settled against observed lines is done.

A finding's `severity` survives checking only on a `verified` verdict and is
`unknown` otherwise, `contradicted` included — a refutation weighs an impact
for something that is not the case. What the producer stated is kept in
`declared_severity` beside `severity_rationale`, so the assessment is not
discarded, only prevented from reading as established.

### Reading again, mid-run

A run may be given an `observer`: a host callable that reads on the run's
behalf when the loop cannot stand behind its sources. It is asked when the
state the run read has moved, or when an evaluation's next action is
`observe_again`, and only while passes remain. The request names the snapshot,
every source by id and path, the status codes behind the gap and the claims
that rested on them. The answer is `Observation.v1` values and nothing else.

Four rules hold, and they are what make a mid-run read evidence rather than
input:

1. **One snapshot per run.** An observation bound to another snapshot is
   refused and the run ends `tool_error`. A run that mixed two states could not
   say which bytes backed a claim.
2. **A changed source is not swapped in silently.** A re-read that carries
   different bytes is recorded in `metadata.observation_rounds[].superseded`
   with both digests. The lines an earlier claim rested on stay in that
   iteration's `citation_checks`, and a new finding citing the old digest fails
   `digest_mismatch`.
3. **Nothing new is not a retry.** A round that returns nothing, or returns the
   same bytes, does not earn another pass: the run stops `blocked` with the
   round recorded.
4. **Fail closed.** A host that raises — a timeout, an unreachable source, a
   refused observation — ends the run `tool_error`, which is a runtime class
   and explicitly not a verdict about an answer. A budget or a cancellation
   keeps its own reason, because a limit is a control stop and the machinery
   did not fail. A failed round produces no observation, so it cannot become a
   finding.

An observer requires `RunLimits`, for the same reason Atlas-managed readers do:
there is no unmetered read path. What the host returns is charged against the
same output budget as everything else. Enforcement is cooperative in-process,
as it is for a model adapter — the deadline is checked before the call and the
result is accepted only if the budget still allows it, and a synchronous host
cannot be preempted. `run_isolated` wraps the whole run, observer included, in
the parent-enforced hard deadline; the observer must be picklable to go there.

New material reaches the producer through the prose `observations` channel and
the evidence base separately. The two stay apart: the text is context and
nothing turns it back into an observation, while the base is what
`check_finding` grades against.

`next_action` is the instruction as data: one `kind` from a closed vocabulary,
the `gap_codes` it addresses, the `actor` who can carry it out, and the
`details` that actor needs — available source ids, the expected sentence, the
failing statuses. It is `null` only when nothing is outstanding, including on a
run that stops `blocked`, where the action is the host's (`observe_again`)
rather than the producer's. The kinds are listed in precedence order: the first
that applies is the one named, because a findings block that cannot be parsed
makes every question about an individual citation moot, and a source that has
moved cannot be re-cited at all. `suggested_adjustment` says the same thing in
English and is for a person; adapters branch on `next_action`.

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

The lifecycle is versioned. A run document carries
`state_machine: "atlas-state-machine.v1"`, and the whole table — statuses,
legal transitions, stop reasons, classes and exit codes — is published as data
in `schemas/atlas-state-machine.v1.json` for a consumer that cannot import
Python. `atlas_core/machine.py` enforces it: a transition outside the table
raises rather than being recorded, and `status` and `stop_reason` are written
together from one entry so they cannot disagree.

Terminal runs expose `status`, `stop_reason` and `stop_class`:

| Status | Stop reason | Class | Meaning |
| --- | --- | --- | --- |
| `done` | `passed` | evaluation | The answer was graded and met its gate. |
| `done` | `insufficient_evidence` | evaluation | The answer was graded and its claims were not established against what the run read. |
| `done` | `blocked` | control | A source the run read has moved or vanished, whether or not a finding cited it, or HEAD moved under the run. The ground moved; re-wording cannot repair it. See `metadata.drift`. |
| `done` | `max_iterations` | control | A gap remained that another pass could have acted on, and the bound stopped the run from trying. |
| `done` | `no_progress` | control | Nothing was left that another pass could change, so a further iteration would fail the same way. |
| `done` | `budget_exhausted` | control | A declared limit other than the iteration bound was reached. |
| `need_user_approval` | `approval_required` | control | The task appears to require mutation. |
| `failed` | `tool_error` | runtime | A model adapter raised, or returned a result that breaks the adapter contract. |
| `cancelled` | `cancelled` | control | The run was stopped from outside before it reached a verdict. |

`stop_class` is the distinction that matters most, and it is derived from
`stop_reason` rather than stored beside it:

- `evaluation` — an answer was produced and graded, and this is the grade.
- `runtime` — the machinery failed, so the run's ending is not a verdict about
  an answer. An evaluation from an earlier iteration may survive in the record;
  it was not promoted to the run's result.
- `control` — a bound, a human or a cancellation ended the run. Any grade it
  carries is provisional: the loop stopped before it was finished, not because
  it was.

`budget_exhausted` and `cancelled` are declared and **not yet produced** by any
code path; they are reserved by the remaining P0.3 work so the vocabulary a
consumer codes against does not grow every time a limit lands. A test names
them, so the gap is recorded rather than implied.

`no_progress` has three forms, and `metadata.no_progress.reason` says which:

- absent — the a-priori form: the evaluation found nothing another pass could
  act on at all.
- `identical_model_output` — a bounded run whose provider returned exactly the
  same bytes twice.
- `unchanged_feedback` — a bounded run whose two passes failed in the same way.
  The wording moved and the failure did not, so the feedback the producer would
  receive next is the feedback it has already had. Compared on the next action,
  the gaps it addresses and the claims still unsupported; the quality score and
  the prose are deliberately excluded, because a score that moves by a rounding
  step while every gap stands is not progress.

Both output-comparing forms are **bounded runs only**. The unbudgeted path
keeps its 1.0 verdict semantics, so a legacy run that spends every pass on a
gap another producer could have closed still reports `max_iterations`.

Adapters must use `stop_reason`; they must not infer completion semantics from
prose output. The text form of a run is rendered from the run document by
`render_run_text`, so it is a view of that document rather than a second source
of truth.

### Migration from the pre-v1.1 vocabulary

Two spellings changed, and one of them split:

| Was | Is | Why |
| --- | --- | --- |
| `failed` | `tool_error` | The status and the reason were the same word, so nothing in the pair said that the failure was the machinery rather than the answer. |
| `no_actionable_retry` | `insufficient_evidence`, `blocked` or `no_progress` | One name covered three situations that ask a reader for different things: look at the evidence, observe the source again, or accept that the loop had nothing left to try. |

`schemas/atlas-run.v1.json` still accepts both old spellings, so a run document
stored before the change remains valid; nothing emits them any more. A document
without a `state_machine` field is from before the change and uses the old
vocabulary. The mapping is published as `legacy_stop_reasons` in the state
machine declaration.

The iteration bound is now reported only when it actually bound something. The
previous controller chose `max_iterations` on whether a formatting section was
missing, so a run that spent every pass on an evidence gap — a gap another pass
could have acted on — reported instead that it had nothing left to try.

### CLI exit codes

`atlas run` maps the terminal state to an exit code, so a script can branch
without parsing output:

| Code | Meaning | Stop reasons |
| --- | --- | --- |
| 0 | The answer passed its quality gate. | `passed` |
| 1 | The machinery failed. | `tool_error` |
| 2 | The run finished without passing. | `insufficient_evidence`, `blocked`, `max_iterations`, `no_progress`, `budget_exhausted` |
| 3 | A mutation needs explicit approval before anything runs. | `approval_required` |
| 4 | The run was stopped from outside before it reached a verdict. | `cancelled` |

The codes are derived from the state machine, not kept by hand, so a new stop
reason cannot fall through to the failure code and look like a crash. An
unrecognised stop reason — a document from a newer version, say — still exits
1.

Exit 1 means the machinery broke and nothing was graded. Exit 2 is not an
error: the loop stopped honestly rather than claiming an answer it could not
support, and a `repo_review` with no observed sources is the common case. The
two must not be collapsed; a script that treats every non-zero code as a crash
will page someone for an honest `insufficient_evidence`.

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


### Optional cooperative run budget (P0.3, partial)

`AtlasController.run(..., limits=RunLimits(...))` shares one `RunBudget` with
its model adapter (`budget` keyword). Model calls, reported *actual* aggregate
`metadata["usage_tokens"]`, and UTF-8 output bytes are charged across retries.
An adapter that does not report nonnegative usage fails as `tool_error`, not a
made-up zero. The same budget exposes `reserve_tool()` for trusted nested tool
adapters, but no host tool gateway is wired yet; direct calls inside an
arbitrary Python adapter cannot be metered or sandboxed by Atlas Core.

The monotonic wall deadline is checked before and after synchronous stages.
**This is not an in-call timeout**: the model adapter itself must enforce the
passed `budget.deadline` while blocked on network/provider work. With no
adapter deadline enforcement the work can run past the wall limit before Core
regains control. A budgeted run does not call the currently unmetered memory
writer. The limits are explicit opt-in; P0.3 resource and write-safety boxes
remain open until tool integration and strict default enforcement exist.
