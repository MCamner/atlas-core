# Atlas Loop API Contract

Atlas Core 1.x keeps its public Python types, JSON documents, stop semantics,
and adapter boundaries stable. Incompatible changes require a new major
version or a new schema identifier.

## The append-only event log

`AtlasController(..., events=sink)` records what a run did, when it did it.
`None` is the default and changes nothing: the log records, it decides nothing,
and a run with one produces the same document as a run without.

`JsonlSink(path)` is the durable one — one JSON object per line, opened in
append mode, flushed and fsynced per write. A crash truncates the last line
rather than corrupting the file, and `read_jsonl` drops a torn final line while
raising on a malformed line anywhere else: the first is interruption, the second
is corruption.

**A call is two events**, `call_started` and `call_finished`, joined by a
`call_id` the log issues. That is the only way a reader can tell three
situations apart:

| what the log holds | what it means |
| --- | --- |
| no `call_started` | the call never began |
| `call_started` alone | it began; the outcome is **unknown** |
| both | it began and the outcome is recorded |

`call_states(events)` returns that, and `unfinished_calls(events)` returns the
middle case. A design with one record per call collapses it into one of the
others, and both readings are dangerous: "failed" invites a retry that repeats a
side effect the first attempt may already have had, and "never happened" is
worse. There is no `unknown` outcome value — `unknown` is the absence of a
report, not something anything writes.

Nothing rewrites an event. The log assigns the sequence number, a call cannot
be finished twice or finished without being started, and an `observation_recorded`
event for a source already recorded is a **new** event carrying both digests —
a source that changed under a run is something the log shows rather than hides.

Reading tolerates a torn final line; **appending does not**, and the two cannot
make the same allowance. The next whole object would be concatenated onto the
fragment and become one invalid line in the middle of the file, taking every
following event down with it. `JsonlSink` therefore checks the tail when it is
built — where the destination is chosen, not on the write that would do the
damage — and raises `TornLogTail`. `JsonlSink(path, truncate_torn_tail=True)`
drops the fragment, which is the only operation that leaves the file consistent
with how reading already treats it. A last line that *ends with a newline* and
does not parse is corruption, not interruption, and always raises.

Accounting is not part of a call. A model call is finished when the provider
returns a usable reply; charging tokens against the budget happens after it and
can fail on a reply the provider delivered perfectly well. The run document is
where that failure belongs, and the call keeps the outcome it actually had.

`run_started` binds a resumable run to digests of its task, initial prose
observations and evidence manifest, plus the snapshot id and iteration bound.
Raw observations remain outside the log. A host that resumes supplies them
again, and Core rejects a changed digest or snapshot rather than reconstructing
source bytes from persistent metadata.

Payloads are masked by `redact_document` before they are written, because this
file persists whether or not anyone exports the run. The task reaches the log as
a digest rather than as text, and a call's input as `input_sha256`. — of the
**whole** input: for a model call, everything the adapter is handed except the
budget and tool handles; for a read, the whole `ObservationRequest`. A digest
over part of the input would say "same" for calls handed different things.

### Safe read-only resume

`AtlasController(..., events=JsonlSink(path)).resume(task, run_id=..., ...)`
resumes one interrupted run from a shared JSONL file. It holds an advisory lock
for that run id while it re-reads, validates and extends the log. Other run ids
in the same file are independent.

Resume appends `interrupted` and `resumed`, preserves the run id and continues
the event sequence. Replay starts the bounded read-only loop from its supplied
initial state. It is allowed only when the task, initial observations,
snapshot, evidence digests and iteration bound match `run_started`. An
unfinished call must declare `idempotent: true`; otherwise Core raises
`ResumeRefused`. Read tools and observer reads are idempotent. A model adapter
must opt in explicitly; `StubModelAdapter` does because it is deterministic.
Memory writers are refused because their prior outcome is not represented in
the event log. A run with `run_stopped` is complete and cannot be resumed.

## Versioned contracts and migration

`atlas_core.contracts` names every document this package emits or accepts, at
which version, and **who may write each field**. The rule it writes down is one
this repository has enforced case by case since P0.2: the producer supplies a
claim, the checker assigns a verdict, the host says what was read, the core owns
the run's identity and where it stopped. Scattered across modules that rule was
still true but could not be read, and a rule nobody can read is one a future
change breaks without noticing. A test binds the table to the schema files:
every declared property has an owner, and every owner names a property that
exists.

What may change inside a version is stated in `contracts.COMPATIBILITY`. The
short version: a version may gain an optional property; it may not gain a
required one, lose a property, narrow a type, or **change what a field means
while keeping its name**. The last is why the rule is written down — it happened
once, to `quality_score`, which went from a weighted score to a share of met
criteria under an unchanged name and type. `score_method` exists because of
that, and it is required in `Evaluation.v2`.

`migrate_run(document)` turns an `atlas-run.v1` document into `atlas-run.v2`,
returning the document and a `MigrationReport`. Three rules, each with a test
rather than a comment:

- **Nothing is dropped.** Every source key is either mapped to a v2 field or
  kept *with its value* in `migration.unmapped`. `report.is_lossless` is false
  when anything had to be parked.
- **Nothing is invented.** A v2 field the source could not have had is `null`
  and named in `migration.not_recorded`. `actions` is the sharp case: an empty
  list would state that the run performed nothing. A missing `score_method`
  becomes `unknown`, never today's method — a document old enough to lack the
  field is old enough to hold the weighted score.
- **An incomplete source is migrated anyway, and says so.** A field the source
  schema required and the document lacked is recorded in `migration.missing`.
  A field `Run.v2` requires that the result does not carry is recorded in
  `migration.unfilled`, and `report.is_complete` is read off *that* — the two
  are different questions, because a source can hold a key whose value is not
  something the target field can contain, and then the key was neither absent
  from the source nor present in the result. The document does not validate
  against `atlas-run.v2`, which is the honest outcome: a default here would be
  indistinguishable from a value the run produced.

A document that does not name its own contract raises `UnknownSourceSchema`.
Every rule above is relative to a source contract, so guessing the source from
its shape would make all three guesses.

**The loop still emits `atlas-run.v1`.** Migration is defined and tested; moving
the runtime onto v2 is a separate change with separate consequences for every
consumer. `Action.v1` and `Approval.v1` are contracts for information that does
not exist yet — nothing records actions, and nothing can grant an approval.
`Approval.v1` makes a grant unstateable without `binds_to`, so an approval can
never be a bare boolean that outlives what it approved.

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

The observer receives the run's own budget: `observe(request, *, budget)`, the
same `RunBudget` a model adapter gets. It travels beside the request rather
than inside it, because the request is what `call_started.input_sha256`
digests and the budget is a handle to the run, not input. An implementation
reserves a tool call per read and checks the budget between reads.

**The first read.** `run(..., evidence=EvidenceBase(snapshot), observer=...,
read_first=True)` asks the observer before iteration one, with the review
plan's patterns (none for an un-narrowed task), so the first answer is graded
against sources. The round follows the four rules above and is logged as an
`observe` call and an `observation_recorded` event at iteration 0. Without
`read_first` a run starts from what it was handed and reads when an
evaluation names a gap.

**`--repo-path` is evidence.** In a bounded CLI run, `--repo-path DIR` hands the
run an empty evidence base bound to `take_snapshot(DIR)` and a
`FilesystemRepoObserver` with `read_first`. The observer resolves the plan's
patterns (shallow globs; `**`, `..` and absolute patterns are ignored), re-reads
paths the run asks for, and on a first request that names nothing reads the
fixed surface the prose adapter used. Each read goes through
`collect_observation_safely` — a contained name and an `O_NOFOLLOW` open — and
is bounded at 256 KiB per source and 8 sources per round; patterns take turns
so a broad one cannot crowd out the rest. A source that is refused, too large,
missing, unreadable or not a file is not read and so is not evidence, and costs
no tool call when that is known before the read. A budget or deadline that runs
out mid-round ends the run under rule 4; the round's reads are discarded.
`--unsafe-legacy-unbounded` and `--repo` keep the prose channel.

A task that narrows to a review topic is now graded as a review: its sources
are evidence, so the plan's criteria apply. The rule-based executor asserts no
findings, so without a model producer such a run ends `no_progress` with
`no_on_topic_finding` where it used to pass on prose. That is the gate doing
its job, not a failed read.

Known limits: the byte limit applies where a source is collected. The drift
gate's re-verification and the citation reader re-read a source without one,
so a file that grows after it was observed is read in full once to find out it
changed. A re-read round re-reads every source the run holds, one tool call
each, because the drift gate needs all of them to verify again.

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

`metadata.non_deterministic` is present exactly when a live provider produced
the output: `{"reason": "live_model_provider"}`. It means the document cannot
be reproduced from itself — the same prompt to the same model may answer
differently, and the model behind a name can change without the name doing so.
It is written by the adapter and the controller, never read out of the model's
own text, and it is absent for a scripted adapter and for a run with no
adapter. `metadata.model_result.metadata.determinism` carries the same fact per
call. See `docs/live-smoke.md` for what a live run has actually been observed
to do.

`LiveModelAdapter(..., capabilities=[...])` declares the tool names the model
may ask for. It is empty by default, it is a whitelist, and it can only narrow
what `ToolGateway` already allows — a declared `write` or `network` tool is
still denied, and a declared name that is not registered is still denied.
`invoke_tool(gateway, name, arguments)` is the only path, and it takes the
gateway rather than holding one: a gateway kept across calls outlives the
budget that made its calls metered. `metadata.model_result.metadata` records
`tools_declared`, `tools_invoked` and `tool_gateway`. Nothing in the package
calls `invoke_tool`, so `tools_invoked` is `0` on every run this version
produces.

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
PR #29 introduced it as a cost rule — another provider call costs money. As a
contract rule it does not depend on anyone counting: a producer that has been
told this and answered it has answered it. A caller written against 1.0 that
drives unbudgeted runs will see `no_progress` where it saw `max_iterations`;
the evaluation is unchanged, and the run stops on an earlier iteration.

The narrower byte-equality rule beside it is still bounded-runs-only, and
deliberately so. Byte equality says a provider returned the same string, which
is a statement about spend; the failure signature says the feedback would
repeat, which is a statement about the contract.

### Tool adapter contract

`ToolDefinition` declares `capability`, `allowed_routes`, `input_schema`,
`output_schema`, `timeout_seconds`, `sandbox`, `idempotent`, `max_attempts` and
`retry_on`. The gateway rejects unknown tools, every write/network capability,
route mismatches and malformed input before the handler runs. Output must be
strict JSON and match its schema. The supported schema subset is `type`,
`enum`, object `required`/`properties`/`additionalProperties`, and array
`items`; unsupported type declarations fail closed.

Every attempt consumes the shared run budget and is a separate event-log call.
More than one attempt requires `idempotent=True`; a read capability defaults to
idempotent for backward compatibility but that default does not enable retry.
The controller installs its selected route on the gateway before a model can
invoke a tool.

`in_process` supports nested tool calls with the same gateway and budget. Its
timeout is cooperative: a synchronous handler cannot be preempted and an
overrun is reported when it returns. `isolated_process` is the hard POSIX
boundary: one child session, capped JSON IPC and process-group termination at
the smaller of the tool timeout and remaining run deadline. Nested calls are
refused in that mode because copied accounting is not shared accounting. This
is process isolation, not a filesystem/network privilege sandbox.

### Run inspection and export

`atlas run --event-log PATH` appends the run's `atlas-event.v1` records to an
explicit JSONL destination. `atlas inspect RUN_ID --event-log PATH` selects one
run, validates its schema, identity, contiguous sequence and terminal-event
placement, then renders a short report. `--json` emits the published
`schemas/atlas-inspect.v1.json` contract with
the route, iteration count, observed source IDs, unresolved evidence gaps,
unfinished calls, stop reason, call summary and the selected events.
`source_details` (optional in the schema, so a consumer of `sources` is
unaffected) gives each source's `path` and the `content_sha256` of the bytes the
run last graded; a supersession replaces the digest and `events` keeps every
reading. A log written before `observation_recorded` carried paths reports
`unknown`.

Inspection never repairs history. A missing run, malformed JSON, non-object
record, wrong schema, forged event/call identity, discontinuous sequence, duplicate
start/stop, a call outcome without exactly one preceding start, malformed
inspection payload shapes or a stop before the final event returns exit code 1
with a diagnostic on stderr. A run without `run_stopped` is reported as
`interrupted`; an unfinished call remains `unknown`, never inferred as failed.

One JSONL may contain several runs when writers are serialized through the
Python API. Concurrent writers are refused, not interleaved: a durable run or
resume holds `<log>.writer.lock`, and a second one gets `EventLogInUse`. The
CLI runs one run per event log (see Host run API).

### Host run API (v1.4)

A host that runs Core as a child process drives a run through five commands.
All of them read the same durable event log; none of them is a second record
of the run.

| Command | Does | Exit |
| --- | --- | --- |
| `atlas create` | Prints a fresh run id. Writes nothing. | 0 |
| `atlas run TASK --run-id ID --event-log PATH` | Runs under that id. An id the log already holds is refused. | as `atlas run` |
| `atlas status ID --event-log PATH [--json]` | `atlas-status.v1`: `not_found`, `running`, `finished` or `interrupted`. | 0; 1 on invalid history |
| `atlas cancel ID --event-log PATH [--json]` | Asks the run to stop. Allowed before the run starts. | 0; 2 if already finished/interrupted |
| `atlas events ID --event-log PATH [--follow] [--timeout S]` | Prints the run's `atlas-event.v1` records as JSONL; `--follow` streams until `run_stopped`. | 0; 2 interrupted or timed out; 1 not found without `--follow` |

Run ids are 1–128 characters of `A-Z a-z 0-9 . _ : -`, starting with a letter
or digit. `--run-id` requires `--event-log`.

A fresh run with a `JsonlSink` holds `<log>.<sha256(id)>.lock` from before
`run_started` until after `run_stopped`. `running` means a process holds that
lock; a history with no stop and no held lock is `interrupted`. A cancel request
is the permanent marker `<log>.<sha256(id)>.cancel`, never an event: the run
records `run_stopped` with `cancelled` when it honours the request, and that
is the fact the log keeps. Cancellation is cooperative and is checked at the
run's budget boundaries; the public CLI's worker deadline stays the hard bound.

Every exit from a run, including one before the first iteration, appends
`run_stopped`.

**One run per event log.** `atlas run --event-log PATH` refuses a log that
already holds a run (exit 1, nothing written). A host stores `(run_id,
event_log)` and uses that pair for every later command. This is a refusal of
shared-log concurrency, not support for it.

**A lost worker is sealed.** When the public CLI kills its worker (wall
deadline, output cap, interrupt) or cannot read its result, the parent takes
the log's locks, drops a torn tail the kill left, and appends `run_stopped`
with `recorded_by: "cli_parent"` — preceded by `run_started` if the worker
never wrote one. The CLI result then carries the same stop reason as the log.
With `--event-log` and no `--run-id`, the parent allocates the id so it can do
this.

**A lost result is not rebuilt.** If the worker had already logged its stop,
the run finished and only its `atlas-run.v1` was lost on the way back. The log
is left untouched and still decides the run state (`atlas status`, `atlas
inspect`). The parent has the terminal event but not the answer or the
evaluations, so it prints no run document: stdout is empty, the exit code is
1, and stderr carries the diagnostic — one JSON object with `--json`:

```json
{"error": "worker_result_unavailable", "run_id": "…", "event_log": "…",
 "logged_stop_reason": "passed", "transport_error": "WorkerProtocolError",
 "message": "…"}
```

The event log decides the run state; the transport decides whether the CLI
can deliver the run document.

### Optional cooperative run budget (P0.3, partial)

`AtlasController.run(..., limits=RunLimits(...))` shares one `RunBudget` with
its model adapter (`budget` keyword). Model calls, reported *actual* aggregate
`metadata["usage_tokens"]`, and UTF-8 output bytes are charged across retries.
An adapter that does not report nonnegative usage fails as `tool_error`, not a
made-up zero. The same budget exposes `reserve_tool()` to the Atlas-managed
gateway. Direct calls made around that gateway by arbitrary Python remain
outside Core's metering and process policy.

The monotonic wall deadline is checked before and after synchronous stages.
**This is not an in-call timeout**: the model adapter itself must enforce the
passed `budget.deadline` while blocked on network/provider work. With no
adapter deadline enforcement the work can run past the wall limit before Core
regains control. A budgeted run does not call the currently unmetered memory
writer. The limits are explicit opt-in; P0.3 resource and write-safety boxes
remain open until tool integration and strict default enforcement exist.
