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

### What a review is asking

A route that reviews a repository carries a **review plan** in
`plan.review`: the snapshot the review is about, the question in one
sentence, and the glob patterns that question needs. A route with a goal and
no question carries `null`, as does a review with no snapshot to be about.

Three properties are worth stating, because each is a choice that could have
gone the other way:

- **The plan binds to a snapshot; it does not take one.** Taking a snapshot is
  reading, and reading is the host's. The plan records which state the whole
  review is about, so an answer can always be traced to one.
- **Sources are patterns, not paths.** Core does not list directories any more
  than it opens sockets. The host resolves a pattern and reads what it finds,
  which is the same division of labour the observation loop already uses — and
  the reason this reuses that loop instead of growing a second one.
- **A task that matches no topic is reported as not narrowed.** The question is
  then the task itself and no sources are named. Inventing a plausible question
  would send a host reading files nobody asked about, and then grade the answer
  against a question nobody posed.

A pattern the plan named is answered when some observation sits under it, or
when a host was asked to resolve it and came back — with nothing, if the
repository has no such file. Core cannot tell "no such file" from "not read
yet" without listing the directory; the host can, and a completed round is
that answer. Until then the criterion `plan_targets_read` is unmet, the gap
code is `plan_targets_unread`, and the next action is `observe_again` naming
the patterns still outstanding.

Topic selection is **keyword matching against a declared vocabulary**. It is a
real mechanism and a narrow one. There is no model in it, and a run whose task
uses words the vocabulary does not carry will report `unknown` rather than
guess.

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

Criteria come from two places: the route, and — since P1.1 box three — the
**question**. A route declares what any review owes; it cannot declare what
*this* review owes, because before the review plan existed there was no
"this". When the plan narrowed to a topic, `findings_are_on_topic` is added,
and its requirement text carries that question verbatim: at least one finding
must be settled **in its favour** against a source the plan named — the source
its claim was *checked against*, not one it merely cites. A finding may
legitimately cite more than one source, and a spare citation is not a claim: a
claim settled about `README.md` does not become relevant to the credentials
question by also pointing at `settings.env`.

**Read the criterion for what it checks.** It is a relevance gate over the
source, not a test that the question was answered, and it is named for the
first rather than the second. A verified claim that `settings.env` contains
`TIMEOUT=30` is settled and is about a source the credentials question named;
it says nothing about whether a password is committed, and it passes. Deciding
whether a settled claim *answers* a question is entailment — the same problem
`claim_check` declines to guess at — and a guess made at the gate would sit
behind a PASS rather than beside a limitation. The requirement text carries
the question so the distance between the gate and the question stays visible
in the run document. P1.1 box three is open for that distance.

**Past relevance, where a topic has declared what would count.** A
`ReviewTopic` may list the literals that bear on its question — `secrets`
declares `password=`, `token=`, `api_key=` and so on. Where it has,
`findings_answer_the_question` is added beside the relevance gate, and a
settled finding must name one of them. A verified claim that `settings.env`
contains `TIMEOUT=30` clears relevance and fails this.

The judgement is **declared, not inferred**: written once, per topic, where it
can be read and disagreed with. Deriving it from an arbitrary claim at grading
time is entailment, which needs a model. Two limits follow, and both are
tested rather than only written down. A topic that declares nothing is held to
relevance alone — a list assembled to have a list would be worse than none.
And a credential that does not name itself, a bare access key or a base64
blob, matches nothing declared and is a miss; the run stops rather than
passing on a claim about something else.

`contradicted` does not satisfy it. A refutation says the producer was wrong,
which is worth knowing and is not the same as the question being settled by
what it wrote; a producer that wants to establish a negative can claim
`source_lacks_literal`, which a verified verdict then carries.

A task the plan could not narrow is not held to a question. There is nothing
to be off-topic about, and holding a broad task to a question nobody posed
would punish it for being broad.

The consequence worth stating: a review that **asserts nothing** no longer
passes a narrowed review. It meets every criterion about what findings are
worth — there are none to be worth anything — and it settled nothing about
what it was asked to look at. The gap code is `no_on_topic_finding` and the
next action is `answer_the_question`, the producer's: the sources are already
in hand and what is missing is a claim about them. That instruction aims past
the gate on purpose; asking for the floor would be asking for the cheapest
thing that clears it.

`repo_review` declares `plan_targets_read`, `sources_documented`,
`findings_are_checkable`, `citations_hold`, `claims_are_settled`,
`recommendation`, `next_step` and `confidence`. A route that checks nothing
against a source declares
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

A run without an evidence base is measured the way it was in 1.0: a finding
counts as covered when it **names** a source that was read, and
`evidence_coverage` reports that share. Nothing on that path compares a claim
against the source's contents.

It therefore **cannot clear the gate** of a route that declares
`claims_are_settled`. Naming a file is not evidence about what the file says,
so a false claim and a true one are indistinguishable there, and a criterion
reported met while no check ran would be the run document asserting something
nobody established. The gap code is `claims_not_checked`, all three evidence
criteria go unmet, and the next action is the host's: collect observations and
pass them as `evidence`. Re-wording cannot close it, so no iteration is spent
trying.

Until that rule landed, a factually wrong statement mentioning `README.md`
passed this gate at 0.9. It no longer does.

A review that records its sources and **asserts no finding** still passes.
There is nothing to settle, `evidence_coverage` stays `null` rather than 1.0,
and the claim ledger is empty.

`citation_checks` is empty for a run with no evidence base, and
`evidence_base` in the run document is `null`, so a reader can always tell a
checked run from an unchecked one.

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

### A live model provider (P1.2, partial)

`atlas_core.adapters.build_model_adapter()` returns a configured adapter or
`None`. `None` is not an error and not a fallback performed inside the adapter:
it is the absence `AtlasController` has always read as "use the deterministic
executor".

That is how two rules hold at once. A **missing key is a configuration state**,
answered by `None`. A **failing request is a request outcome**, and the
controller stops with `tool_error` rather than publishing a deterministic
answer as though a model had written it. A configuration that is stated and
wrong — an unknown provider, a non-numeric timeout — raises, because silence
would leave a typo running the deterministic path unnoticed.

Configuration is read from the environment: `ATLAS_MODEL_PROVIDER` (`ollama` or
`openai_compatible`), `ATLAS_MODEL`, `ATLAS_MODEL_ENDPOINT`,
`ATLAS_MODEL_API_KEY`, `ATLAS_MODEL_TIMEOUT`. A caller may pass a dict instead.
The key stays on the config: it is not in `ModelResult.metadata`, not in the run
document, not in the failure record, and not in the dataclass `repr`.
`ProviderConfig.describe()` is what anything else may see.

Token counts a provider reports are mapped to `metadata["usage_tokens"]`, which
is the field `RunBudget` charges. Absent counts report nothing rather than zero.

The prompt is bounded by `PromptLimits`, in **characters** — counting tokens
needs a tokenizer per provider, which this package does not carry. Observations
are what gives way when the bound bites: truncated per source first, then
dropped whole, in the order the run holds them. What is shown is always a
**prefix** of that order: the first source that cannot be shown ends the
selection and the rest are counted as omitted, because the omission notice
names no source and so means something only if the shown set is the first N.
Every cut is stated in the
prompt the producer reads *and* counted on the result, so
`metadata.model_result.metadata` carries `prompt_complete`,
`observations_truncated` and `observations_omitted`. The instruction is never
cut, so a bound that cannot hold the task, question and feedback raises rather
than being exceeded.

The reply is asked for in a schema and checked locally either way. The schema
(`schemas/atlas-model-output.v1.json`) goes in the field each provider reads —
`format` for Ollama, `response_format` for an OpenAI-compatible endpoint — and
wraps the prose and the findings in one object, because a schema over the reply
means the reply is JSON and the prose half is not. The adapter reassembles the
markdown the loop already reads. `LiveModelAdapter(..., structured_output=False)`
sends no schema field.

Asking is not getting: an endpoint can accept the field and ignore it, so the
reply is checked on every call. `output_conformed` is a claim about the whole
reply — the envelope holds, carries no field the schema forbids, and every
entry is one `structured_findings` can use. The last of those is put to
`atlas_core.evidence`, which stays the sole authority on what a finding must
look like.

**A reply of the wrong shape does not raise.** It reaches the evaluator, which
reports `malformed_findings` with `repair_findings_block` — a producer error
the next pass can fix, not a `tool_error` that ends the run. An envelope that
held is rebuilt even when its entries are unusable, so they reach the reader
that reports them; an envelope that did not hold passes through untouched.
`metadata.model_result.metadata` carries `output_schema`, `output_schema_sent`,
`output_conformed` and, when it did not conform, `output_schema_gap`.

A producer that was asked for a findings block and wrote none gets the same gap
and the same next action. Nothing in the output distinguishes it from a review
that honestly asserts nothing, so `evaluate()` takes
`structured_output_required` and the controller sets it from what the adapter
recorded about its own request. Without a schema on the wire nothing changes,
and neither a handwritten `atlas-findings` block nor an explicit empty
`findings: []` counts as missing. `no_sources_observed` outranks it, because a
run with nothing to read cannot be repaired by rewriting the answer.

What identifies a live run carries no secret. `config_id` is a digest over
provider, model, endpoint, timeout and whether a key is set — the endpoint is
hashed rather than published because a URL can carry a token in its query
string, and the key is not hashed in at all. `provider_model` and
`provider_fingerprint` record what the provider said it served, beside the
`model` that was asked for, and are absent when it reports none.

A failed request raises a named exception — `ProviderRateLimited` (with the
provider's own `retry_after` when it gave one, `None` otherwise),
`ProviderTimeout`, `ProviderUnreachable`, `ProviderRefused`,
`ProviderBadResponse` — and the controller records the type name in
`metadata.failure.error`, so a caller can tell a rate limit from an unreachable
daemon without parsing prose. **None of them retry inside the adapter**: that
would spend wall-clock the `RunBudget` cannot see, and the loop owns whether
another attempt is worth it.

Not yet, and stated so a caller does not assume otherwise: structured output is
not validated against a schema and no schema is sent to the provider, results
are not marked non-deterministic, and the adapter offers the model no tool.

### What another pass rests on (P1.1)

A `next_action` declares what a retry of it would rest on, in
`atlas_core.state.RETRY_CLASSES`:

- **`restatement`** — everything the next pass needs is already in the run. The
  fault is in what was written: a block that will not parse, a claim stated so
  it cannot be settled, a missing section, a finding about the wrong source
  while the right one sits in the evidence base. Changed feedback is what such
  a pass needs, and it is enough.
- **`investigation`** — the next pass needs material the run does not hold.
  `observe_again` is the only one. A run that cannot get it — no observer, or a
  round that returned nothing new — stops `blocked`, with
  `metadata.blocked.reason` set to `no_new_material`. Feedback cannot produce
  bytes.

A new test result is not a third channel. It reaches a run as an observation
through its own adapter, so it changes the evidence base like any other read. A
changed plan is the other channel, and it is recorded in the run document.

Every kind must appear in the table; an unclassified one is refused at import,
because defaulting it to `restatement` would quietly grant the permissive half.

A run whose feedback repeats stops `no_progress` with
`metadata.no_progress.reason = "unchanged_feedback"`, and
`metadata.no_progress.material` says whether the evidence stood still too.

**This applies to every run.** Before P1.1 it was bounded runs only, because
#29 introduced it as a cost rule — another provider call costs money. As a
contract rule it does not depend on anyone counting: a producer that has been
told this and answered it has answered it. A caller written against 1.0 that
drives unbudgeted runs will see `no_progress` where it saw `max_iterations`;
the evaluation is unchanged, and the run stops on an earlier iteration.

The narrower byte-equality rule beside it is still bounded-runs-only, and
deliberately so. Byte equality says a provider returned the same string, which
is a statement about spend; the failure signature says the feedback would
repeat, which is a statement about the contract.

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
