# Changelog

## Unreleased

Roadmap P1.1, filed item: a question with declared predicates.

- **`findings_answer_the_question`**, beside `findings_are_on_topic` and only
  for a topic that declared what would count. `ReviewTopic.answering` lists the
  literals that bear on the topic's question; `secrets` declares `password=`,
  `token=`, `api_key=` and so on, and a settled finding must name one. A
  verified claim that `settings.env` contains `TIMEOUT=30` clears relevance and
  fails this — the pair the roadmap item named, tested as two runs against one
  file.
- The requirement text lists the literals it will accept, so the bar is not a
  hidden list.
- **Declared, not inferred.** The judgement is written once, per topic, where
  it can be read and disagreed with. Deriving it from an arbitrary claim at
  grading time is entailment, which needs a model, and a guess would sit behind
  a PASS instead of beside a limitation.
- Two limits, each with a test rather than only a sentence: a topic that
  declares nothing is held to relevance alone, and a credential that does not
  name itself matches nothing declared and is a miss. The second fails closed —
  the run stops and asks for an answer.
- When nothing is on topic at all, **both** criteria are reported unmet. Met
  criteria are `declared - unmet`, so naming only the relevance gap would leave
  `findings_answer_the_question` in the met list and in `quality_score` while
  no finding had existed to test against the answering set. The run stopped
  either way; the reporting would have asserted something nobody established.
- `plan.review.answering` is declared in `schemas/atlas-run.v1.json`, so a
  consumer can read what the run was willing to accept as an answer.

Roadmap P1.1 box four: what another pass has to rest on.

- **`RETRY_CLASSES`**, beside the action vocabulary it classifies. Taken
  literally, "require a new observation, a new test or a changed plan before a
  retry" would refuse a producer the chance to fix a malformed findings block,
  which needs nothing new — the bytes are in hand and the fault is in the
  writing. So the contract is stated per action: `restatement` when everything
  the next pass needs is already in the run, `investigation` when it is not.
  Checked at import, because an unclassified kind would default to the
  permissive half.
- Only `observe_again` is an investigation. A run that cannot get the material
  — no host attached, or a round that came back with nothing new — now stops
  `blocked` with `metadata.blocked.reason = "no_new_material"` instead of
  spending passes to fail the same way. A new test result is not a third
  channel: it reaches a run as an observation through its own adapter.
- `metadata.no_progress.material` says whether the evidence stood still as well
  as the feedback. The rule itself is unchanged and still bounded-runs-only:
  widening it would change when an unbudgeted run stops and rewrite the tests
  that hold the 1.0 semantics visible, which is a decision of its own rather
  than part of naming what a retry rests on.
- **Fixed on the way:** `answer_the_question` was ranked ahead of
  `repair_findings_block`. "Nothing on topic" is true whenever nothing was
  settled, which includes every structural failure, so a producer whose findings
  block would not parse was told to answer the question while the reason nothing
  had been read went unmentioned. It now sits second to last, ahead of
  `add_sections` only.

Roadmap P1.1 box two: fixture repositories with an answer key, and what the
numbers say.

- **Two fixture repositories** under `tests/fixtures/`, identical in shape and
  different in content: one with three known defects, one with none. Each
  carries `ground_truth.json`, where a defect is a **predicate the
  deterministic checker can settle** rather than a description. A defect that
  cannot be written that way is not in the key, because a benchmark whose key
  cannot be checked measures the reader's opinion of the output.
- A test checks the answer key itself: every declared defect is present in the
  one repository and absent from the other.
- **`atlas_core/benchmark.py`** scores a run document against a key. Matching
  is exact — same path, kind and text — never by comparing prose, which would
  let a generous reader score a vague sentence as a hit. It reads the run
  document only; recomputing a verdict would be marking the same homework
  twice.
- Measured: findings asserted, verified, refuted and unestablished; defects
  found and missed; precision, recall and evidence-backed share; iterations,
  cost and stop reason. `precision` is `None` rather than `0.0` when a run
  established nothing — zero would read as "wrong about everything", which is
  a measurement, and absent is the honest value.
- **`overstates_completeness`**, the metric that is easy to leave out. A review
  that asserts nothing meets every criterion it owes and passes at a full
  score. That is the right answer to "did your claims hold" and not an answer
  to "is this repository sound", and the two read alike. On the fixture with
  three real defects, an empty review passes with recall 0.0 — for a task the
  plan could not narrow. The same fixture under a task that narrows stops on
  `findings_are_on_topic` instead, and both rows are published, because a
  benchmark has to describe the code it actually runs against.
- **The trailer no longer leaves that impression unremarked.** A passing run
  that graded no claim now says so, and says that it is not a statement about
  the sources.
- **Measured from no observations at all**, not only from a preloaded base.
  Two rows start with the snapshot and nothing read: the plan narrows, the host
  resolves its patterns, and the defect is established against the bytes that
  read returned. The preloaded rows skip the half of the loop that decides what
  to read, and a regression there would leave every one of their numbers
  unchanged.
- `precision` counts findings on both sides of the share. It divided distinct
  defect ids by a count of established findings, so a run that stated one real
  defect twice was reported as half wrong. `found_defects` stays deduplicated,
  because recall is a share of the defects.
- The trailer's "asserted no finding" note is scoped to routes that owe
  `claims_are_settled`. A route that answers a question makes no findings by
  design, and `hej` on the `general` route was being told that nothing had been
  established about sources it never had.
- `docs/benchmark.md` publishes the method, the fixtures, the results and the
  limitations — including that the producers are scripted, so nothing here
  measures a model.
||||||| parent of abe9161 (feat(p11): what another pass rests on, declared per action)

Roadmap P1.1 box three, partly: criteria that come from the question, not just
the route. The box stays open — see below, and ROADMAP.md.

- **`findings_are_on_topic`.** A route declares what any review owes. It cannot
  declare what *this* review owes, because before the review plan existed
  there was no "this": every run of `repo_review` was graded against the same
  list whatever it had been asked. When the plan narrows to a topic, a
  criterion is added whose requirement text is that question verbatim, and it
  is met when at least one finding is settled **in its favour** against a
  source the plan named — the source its claim was *checked against*, not one
  it merely cites. A finding may legitimately carry several citations, and a
  spare citation is not a claim.
- **It is a relevance gate, and it is named as one.** It checks the source a
  settled claim is about, not the subject the claim speaks to. A verified
  claim that `settings.env` contains `TIMEOUT=30` clears it while saying
  nothing about whether a credential is committed. Deciding whether a settled
  claim *answers* a question is entailment, which `claim_check` refuses to
  guess at, and a guess made here would sit behind a PASS instead of beside a
  limitation. `TestWhatTheGateDoesNotDecide` pins the distance.
- `contradicted` does not satisfy it. A refutation says the producer was
  wrong, which is worth knowing and is not the same as the question being
  settled by what it wrote. A producer that wants to establish a negative can
  claim `source_lacks_literal`, which a verified verdict then carries.
- A task the plan could not narrow is **not** held to a question. There is
  nothing to be off-topic about, and holding a broad task to a question nobody
  posed would punish it for being broad.
- **A review that asserts nothing no longer passes a narrowed review.** It
  meets every criterion about what findings are worth — there are none to be
  worth anything — and it has not answered what it was asked. This closes at
  the gate what the trailer could only warn about.
- New next action `answer_the_question`, the producer's, ranked after reading
  and before anything about how good the findings are: an answer about the
  wrong subject cannot be repaired into an answer about the right one, and
  improving its citations would only make it read better. It carries the
  question, the patterns and the source ids already in hand. The instruction
  aims past the gate deliberately — asking for the floor would be asking for
  the cheapest thing that clears it.
- Fixed while adding it: an off-topic answer produced **no** next action at all
  and offered no retry, because the gap was raised after `_next_action` had
  already decided there was nothing to say. A producer can fix this one with
  what the run already holds, so it is now both actionable and named.
- A host round that resolves a pattern for the first time now counts as
  progress even when it finds nothing. The run learned the repository has no
  such file, which it had no other way to learn; it can happen once per
  pattern, because the pattern is then recorded as resolved.
- The severity rule from #36 is unchanged and re-asserted here: an
  unestablished finding keeps `declared_severity` and carries `unknown`.

Roadmap P1.1 box one: a plan that knows what it is asking, and what it needs
to read.

- **`plan.review` on a route that reviews a repository.** The plan a run
  carried was a list of step names — `observe_repo`, `summarize`, `find_gaps`
  — fixed per route and identical for every task that reached it. It said what
  the route generally does; it never said what *this* run was looking into.
  A `ReviewPlan` states the snapshot the review is about, the question in one
  sentence, and the glob patterns that question needs.
- **It binds to a snapshot rather than taking one.** Taking a snapshot is
  reading, and reading is the host's. The plan records which state the whole
  review is about, so an answer can be traced to one.
- **Sources are patterns, not paths.** Core does not list directories any more
  than it opens sockets. The host resolves a pattern and reads what it finds —
  the same division of labour the observation loop already uses, and the reason
  this reuses that loop instead of growing a second one.
- **A task that matches no topic is reported as not narrowed**, with the task
  as the question and no sources named. Inventing a plausible question would
  send a host reading files nobody asked about, and then grade the answer
  against a question nobody posed. Same discipline `Observation.v1` applies to
  provenance.
- New criterion `plan_targets_read` for `repo_review`, gap code
  `plan_targets_unread`, and a next action that is the **host's**: a finding
  cannot be improved into a source nobody read.
- A pattern is answered when an observation sits under it **or when a host was
  asked to resolve it and came back** — with nothing, if the repository has no
  such file. Core cannot tell "no such file" from "not read yet" without
  listing directories; the host can, and a completed round is that answer.
  Without this a plan would wait forever on a file that does not exist and
  every review would end `insufficient_evidence`.
- `ObservationRequest` carries `patterns` and `question`, so a first read has
  something to resolve and a host that can choose has something to choose by.
- Topic selection is keyword matching against a declared vocabulary of five
  topics. A real mechanism and a narrow one; there is no model in it.
||||||| parent of 0b4f532 (feat(p11): fixture repositories with an answer key, and the numbers)

Post-merge review of #36: a citation is not a check, and the run document must
not say it was.

- **Fixed: `repo_review` could pass on the citation-only path.** Where a run
  carries no evidence base, a finding counts as covered when it merely *names*
  a source that was read. That measurement is unchanged and it settles
  nothing, so a route declaring `claims_are_settled` now fails closed there:
  the gap code is `claims_not_checked`, and `claims_are_settled`,
  `citations_hold` and `findings_are_checkable` all go unmet.
- The `passed` itself is **older than #36** and was recorded in
  `docs/api-contract.md` as a known limitation — a factually wrong statement
  mentioning `README.md` cleared that gate at 0.9. What #36 added was a
  positive claim about *why* it cleared it: three criteria reported met beside
  an empty `citation_checks`. Both are closed by the same rule, and the
  contract text that described the hole is corrected.
- A true claim fares exactly the same as a false one there. The rule is about
  what was established, not about what happens to be true; passing a correct
  claim would mean the gate had judged it, and it did not.
- **The vacuous case is kept apart.** A review that records its sources and
  asserts no finding still passes: there is nothing to settle,
  `evidence_coverage` stays `null`, and the ledger is empty.
- The next action is the host's — `observe_again` with
  `details.reason = "no_evidence_base"`. Re-wording cannot produce an evidence
  base, so the retry is not offered and no iteration is spent failing again.
- **`score_method` on every evaluation.** `quality_score` changed meaning under
  an unchanged field name in #36, which a consumer written against 1.0 would
  never have found out. The field names the method: `criteria_met_share` now,
  and a document without the field predates P1.1 and carries
  `weighted_sections_and_length`.
- Five tests encoded the old behaviour, including one whose name asserted that
  a citation-only finding "is verified". None were deleted; each now asserts
  the rule that replaced it, and keeps the point it was originally making.
  `tests/test_citation_only_fail_closed.py` adds the negative regression,
  including the invariant rather than only the instance: no evidence criterion
  may be met while `citation_checks` is empty.

Roadmap P1.1 box three (partly): what it takes to be done, named per route
instead of priced.

- **Exit criteria replace the score as the gate.** A run used to pass by
  collecting enough weight: 0.45 to begin with, 0.15 for clearing three hundred
  characters, a little per heading present, times an evidence factor, against
  `PASS_THRESHOLD = 0.78`. Nothing in that arithmetic said what the route owed,
  and an answer could clear the bar with a section the route had declared still
  missing — a run reporting that it had met its gate while one of its own
  requirements went unmet.
- Each route now declares named criteria in `EXIT_CRITERIA`, and **all** of
  them must be met. There is no weighting, because a requirement that can be
  outvoted by other requirements is not one. `passed` is exactly
  `unmet_criteria == [] and not requires_user_approval`.
- `repo_review` declares `sources_documented`, `findings_are_checkable`,
  `citations_hold`, `claims_are_settled` and its three sections. It does **not**
  declare `substance`: a short review whose findings were settled against
  observed lines is done, and words are not what makes it so. A route that
  checks nothing against a source keeps the length proxy — named, and visible
  in the run document, rather than folded into a sum.
- `quality_score` is now the share of criteria met, and it **reports** rather
  than decides; nothing compares it against a threshold. `PASS_THRESHOLD`,
  `SECTION_WEIGHTS` and the evidence coverage factor are removed, not
  deprecated: a constant that no longer describes the system is worse than an
  absent one.
- The text trailer names what was not met beside the number. A reader who only
  sees a share cannot tell what is still outstanding.
- **No verified severity without coverage.** A producer declares `P1` before
  anything is checked. That number survives the check only on a `verified`
  verdict and is `unknown` otherwise — `contradicted` included, because a
  refutation weighs an impact for something that is not the case. What the
  producer stated is kept in the new `Finding.declared_severity` beside its
  rationale: losing it would discard an assessment, while presenting it as
  established is what must not happen.
- `citation_checks[]` carries `severity`, `declared_severity` and
  `severity_rationale`, so the difference is visible per finding.
- `schemas/atlas-evaluation.v1.json` gains `met_criteria` and
  `unmet_criteria` and redefines `quality_score`;
  `schemas/atlas-finding.v1.json` gains `declared_severity` and redefines
  `severity`.

Roadmap P1.1: a run can read again, mid-loop, without loosening what evidence
means.

- **`AtlasController.run(observer=...)`.** Until now a run's evidence was
  fixed before it started: whatever the loop found missing, it could only ask a
  producer to re-word. A gap that needed a *source* had nowhere to go, so the
  run stopped `blocked` and a human went and looked. The loop now asks the host
  to read when the state it read has moved, or when an evaluation's next action
  is `observe_again`, and only while passes remain.
- **One snapshot per run still.** An observation that arrives bound to a
  different snapshot is refused and the run ends `tool_error`. Asking the host
  for more evidence must not become the way around the rule that a run cannot
  mix two states.
- **A changed source is not swapped in silently.** A re-read carrying different
  bytes is recorded in `metadata.observation_rounds[].superseded` with both
  digests. The lines an earlier claim rested on stay in that iteration's
  `citation_checks`, and a new finding citing the old digest fails
  `digest_mismatch` rather than being re-pointed at content nobody compared it
  against.
- **Nothing new is not a retry.** A round that returns nothing, or returns the
  same bytes, does not earn another pass: the run stops `blocked` with the
  round on record. Re-grading evidence the run has already graded is exactly
  the retry this phase refuses.
- **Fail closed.** A host that raises — a timeout, an unreachable source, a
  refused observation — ends the run `tool_error`, a runtime class that the
  state machine already says is not a verdict about an answer. A budget or a
  cancellation keeps its own reason, because a limit is a control stop and the
  machinery did not fail. A failed round produces no observation, so it cannot
  become a finding.
- An observer requires `RunLimits`, for the same reason Atlas-managed readers
  do: there is no unmetered read path. What the host returns is charged against
  the same output budget as everything else. `run_isolated` carries the
  observer into the parent-enforced hard deadline; enforcement in-process
  stays cooperative, as it is for a model adapter.
- `evaluating → observing → replanning` are new edges in the state machine.
  `observing` already means "the run is reading", so this adds edges rather
  than meanings and the published version is unchanged.
- New material reaches the producer through the prose `observations` channel
  and the evidence base separately. The two stay apart: the text is context and
  nothing turns it back into an observation, while the base is what
  `check_finding` grades against.

Roadmap P1.1, box four (partly): feedback as data, and a retry that has to be
worth an iteration.

- **`next_action` on every evaluation with something outstanding.** The gap
  *codes* were already structured; what to do about them was English in
  `suggested_adjustment`, so a host or a model adapter had to parse prose to
  find out whether to re-cite, repair a block or go and observe a source again
  — the one thing `docs/api-contract.md` tells adapters not to do. The action
  is now data: one `kind` from a closed vocabulary, the `gap_codes` it
  addresses, the `actor` who can carry it out, and the `details` that actor
  needs. The prose stays beside it, for people.
- One action rather than a list, chosen by **precedence, not severity**: a
  findings block that cannot be parsed makes every question about an individual
  citation moot, and a source that has moved cannot be re-cited at all.
  `gap_codes` still carries everything outstanding, so naming one hides
  nothing.
- `observe_again` carries `actor: "host"`. It is the one action a producer
  cannot take — a producer told to try harder against a file that has moved
  would only invent something — and a run that stops `blocked` therefore still
  states a next action instead of leaving the case that most needs a human the
  least served.
- **A bounded run no longer buys an iteration by rewording.** `#29` stopped a
  run whose provider returned byte-identical output; a producer could reword
  its answer, fail in exactly the same way and get another pass. The rule is
  now also stated on the failure: same next action, same gaps, same unsupported
  claims means the feedback the producer would receive next is the feedback it
  has already had. `metadata.no_progress.reason` says which rule fired,
  `identical_model_output` or `unchanged_feedback`.
- The score and the prose are deliberately **not** part of that comparison. A
  quality score that moves by a rounding step while every gap stands is not
  progress, and wording is not a failure.
- Bounded runs only, as in `#29`. The unbudgeted path keeps its 1.0 verdict
  semantics, so a legacy run that spends every pass on a gap another producer
  could have closed still reports `max_iterations`. A test asserts that
  boundary rather than leaving it to be discovered.
- `schemas/atlas-evaluation.v1.json` declares `next_action`;
  `schemas/atlas-run.v1.json` declares `metadata.no_progress`. Both are
  optional additions, so a consumer written against 1.0 still reads a valid
  document.

Roadmap P0.1, the three boxes that were left partly closed: drift that reaches
a run, a citation that can be followed to its lines, and containment and
masking on every path.

- **A run now stops when the state it read moves under it.** `detect_drift`
  has existed since the snapshot work and nothing in a run called it, so only
  half the box was covered, and by accident: checking a citation re-reads what
  it points at, so a *cited* source that moved was caught. A source no finding
  cited, or a HEAD that moved while the model was thinking, was not caught
  anywhere. `AtlasController` runs one gate after grading; a drifted run stops
  `blocked`, and `metadata.drift` records `head_moved`, the per-source
  verification results and the paths behind those ids.
- The gate runs **after** grading on purpose. Refusing earlier would save a
  model call and lose the per-finding record that says which claim rested on
  what moved — and it would fire or not depending on whether the root is a git
  checkout, since an edit there flips clean to dirty. The evaluation survives
  as history; the run still ends `blocked`.
- The text trailer says what moved. A finding can check out against a
  still-fresh README while another source moved, so the trailer could read
  "Status: passed" beside "Stop reason: blocked". It now names the moved paths
  and states that any grade describes the state that was read.
- Where the line sits is asserted, not assumed: a branch label at the same
  commit is not drift, because no byte the run relies on changed. Separation
  between branches is kept by recording the ref and by `EvidenceBase` refusing
  observations from more than one snapshot.
- **Each citation now carries the span it rests on.** `citation_checks[]
  .statuses` gains `line_start`, `line_end` and `quoted` beside the status, so
  a finding can be followed to a `source_id` *and* to the exact lines without
  re-reading the file and guessing which part was meant. The spans come from
  the finding's own citations, never copied from the observation, and a length
  mismatch raises rather than attaching one citation's span to another's
  verdict. `schemas/atlas-evaluation.v1.json` declares the three fields.
- **Containment covers every read.** `Observation.path` refuses an absolute
  form or a `..` component at construction, in both POSIX and Windows
  spelling, so a record naming a file outside its snapshot cannot exist.
  `verify_observation` reads through `read_within` like everything else and
  reports the new result `refused` when a component became a link after the
  name was recorded. It also stops guessing for a source it cannot re-read: a
  `ci` path is an identifier, not a file name, and joining it onto a local
  root could hit an unrelated file and report on it.
- **`confidentiality` is derived from the content** at collection instead of
  staying `unknown` because nobody filled it in: `secret` for a credential
  shape, `internal` for personal data, `unknown` otherwise. Never `public` —
  the detection is narrow, so no match says something about the patterns
  rather than about the source. A caller that states a class is not overruled.
- **Masking covers the whole exported run document**, not only the evidence
  manifest. The prose `observations` channel and the output that repeats it
  back used to leave verbatim, so a run whose manifest was clean could publish
  the same credential one key away. Two tests asserted that leak as known
  behaviour; they now assert the masking.
- Two leaf modules make that possible without an import cycle: `redaction`
  (what is sensitive) and `containment` (where a read may go). Both are needed
  below the collection layer as well as above it, which is exactly why the
  verification read was unprotected while the export was not. `integrity`
  re-exports their names, so its callers are unchanged.

Roadmap P0.3, box one: a versioned state machine, and a stop reason that says
which kind of ending it was.

- Added `atlas_core/machine.py` and `schemas/atlas-state-machine.v1.json`. The
  lifecycle is now a table: statuses, legal transitions, nine stop reasons,
  and for each reason its terminal status, its class and its exit code. The
  schema file is the same table as data, for a consumer that cannot import
  Python, and a test holds the two in step.
- **A stop reason now names its own terminal status.** `AtlasRunState.stop()`
  writes both fields from one entry, so a run cannot report a runtime failure
  while claiming it is done. The controller no longer assigns either field; a
  test greps it to keep that true.
- **Transitions are enforced, not documented.** `enter()` refuses a move the
  table does not allow, including a second terminal move — a failed run being
  able to report itself passed afterwards was one assignment away.
- Every run document carries `state_machine` and `stop_class`. `stop_class` is
  derived from `stop_reason` rather than stored beside it, so the two cannot
  disagree. `runtime` means the machinery failed and the ending is not a
  verdict about an answer; `evaluation` means an answer was graded and this is
  the grade; `control` means a bound, a human or a cancellation stopped the run
  before it was finished. The text trailer says which, and a runtime failure
  now states plainly that nothing was graded.
- `failed` became `tool_error`. The status and the reason had been the same
  word, so nothing in the pair said the failure was the machinery rather than
  the answer.
- `no_actionable_retry` split into `insufficient_evidence`, `blocked` and
  `no_progress`. One name had covered three situations that ask a reader for
  opposite things: look again at the evidence, observe the source again, or
  accept that the loop had nothing left to try. `blocked` is decided from
  `AtlasEvaluation.blocked_by`, a new list of status codes, rather than from
  the prose the evaluator already wrote — a stop reason must not depend on how
  a sentence is worded.
- **Fixed: the iteration bound is reported only when it bound something.** The
  previous controller chose `max_iterations` on whether a formatting section
  was missing, so a run that spent every pass on an evidence gap — a gap
  another pass could have acted on — reported instead that it had nothing left
  to try. `AtlasEvaluation` now separates `retry_is_possible` from
  `should_retry`, which folds the budget in, so the two together say whether
  the bound was the constraint. This closes the inaccuracy recorded under P0.2
  below.
- `schemas/atlas-run.v1.json` widens the `status` and `stop_reason` enums and
  adds two optional fields. It still accepts `failed` and `no_actionable_retry`
  so a stored document stays valid; nothing emits them. The mapping is
  published as `legacy_stop_reasons`, and `docs/api-contract.md` has a
  migration table. A document without `state_machine` is from before the
  change.
- Exit codes are derived from the table instead of kept by hand, so a new stop
  reason cannot fall through to the failure code and look like a crash. Exit 1
  now means only `tool_error`; `cancelled` takes the new code 4.
- `budget_exhausted` and `cancelled` are **declared and not produced by any
  code path yet** — P0.3 boxes two and four. Declaring them now keeps the
  contract stable while the limits land; a test names them and sweeps the
  decision table exhaustively to prove nothing reaches them, so a later PR has
  to come here and delete a line.
- `no_progress` here is the a-priori form: the evaluation found nothing another
  pass could act on. Detecting that two passes produced the *same* output is a
  separate, stronger check that P1.1 owns.
- Negative controls: reordering the bound check behind the evidence verdict,
  classing `tool_error` as an evaluation, dropping the transition check, and
  emptying `blocked_by` each fail the suite. One of them found a real gap in
  passing — the text trailer's failure note keyed on the old spelling and had
  gone silent, with no test to notice.
- 340 tests pass. `mypy` and `pyright` are clean.

Roadmap P0.2, box four: a CI result that can be cited, and can go stale.

- Added `atlas_core/ci.py`. `ci` had been a declared `SourceType` that nothing
  produced, so every CI citation was refused as `unsupported_source_type` —
  the right outcome for the wrong reason. Refusing a source because nobody can
  fetch it is not the same as testing what happens when a fetched one ages.
- `CIRun` records what identifies a run: provider, workflow, run id, ref,
  commit, conclusion and completion time. The digest is taken over exactly
  those, canonicalised, so it changes when the result changes and not when a
  provider reorders its JSON. Only `success` counts as green; `unknown` and
  `in_progress` do not, and an unfetchable field cannot be defaulted into a
  green result.
- CI sources are re-read through their adapter, never from a cache. A cached
  copy would make every CI citation permanently fresh, which is the failure the
  box names. A run re-run red is `stale_source`; so is a re-run that comes back
  green, because identity is the run and not the conclusion it happened to
  produce.
- Re-reading is now per source type. `SourceReader` has one implementation for
  local files that cannot be replaced by a caller — one that could would own
  containment and freshness for every local citation in the run — and hosts
  supply readers for anything else. A source type with no reader is refused
  rather than guessed at. Atlas Core still makes no network calls.
- `AtlasRunState.to_dict` clears the evidence base before `asdict` walks it
  rather than filtering afterwards. `asdict` deep-copies, and a host's reader
  may wrap a network client that cannot be copied at all, so the old order
  raised while rendering a run. Reproduced, fixed, and now covered by a test
  that a negative control showed was missing.

Roadmap P0.2b: deciding whether the source supports the claim.

- Added `atlas_core/claim_check.py`. A finding must declare **what would make
  it false** — a condition over a source the run read — and a deterministic
  checker settles it. The producer says how it could be wrong; code decides
  whether it is, so a model's self-assessment closes nothing on its own.
- Before this, a README containing `pip install atlas-core` backed a finding
  asserting it "saknar helt installationsinstruktioner och nämner aldrig pip",
  with a sound citation and `passed: True`. That finding is now `contradicted`
  and the run does not pass. A finding that declares no condition gets
  `insufficient_evidence` and does not pass either: a sound citation alone is
  no longer enough for `repo_review`.
- **`contradicted` and `verified` are reachable for the first time**, and only
  from a **typed claim** in `claim_check.py`, where the claim *is* the
  predicate: `source_contains_literal` or `source_lacks_literal` over a cited
  source, with the human-readable sentence derived from the object rather than
  written freely. The finding's own `claim` string must equal that derivation,
  so the sentence a reader sees cannot say more than what was settled.
  `finding.py`'s structural guarantee is unchanged.
- An earlier draft let free text pair with a separately chosen predicate. The
  predicate was deterministic; its relevance to the claim was not checked, and
  that broke both directions — a false claim earned `verified` because
  `# Atlas Core` is in the README, and a true one earned `contradicted` for the
  same reason. Deciding a producer-chosen predicate is not deciding the
  producer's claim.
- Free text keeps `insufficient_evidence` and cannot reach `PASS`. A declared
  `claim_check` survives as a diagnostic and yields `condition_supported` or
  `condition_refuted`; neither is decisive, and the names are the point.
  A finding declares a `typed_claim` or a `claim_check`, never both.
- Claims are settled over the **observed line range**, not the file.
  `collect_observation` keeps a bounded excerpt, so searching the whole file
  would let text nobody observed decide a verdict — the same defect
  `quote_outside_excerpt` refuses on the citation side. The derived sentence
  names the range.
- Only a finding with sound citations reaches the claim check. A refutation
  resting on a source the finding cannot point at would be an accusation about
  the wrong file. A stale source settles nothing in either direction.
- Conditions match literal text. A producer-supplied regular expression is
  untrusted input that can hang the checker; a substring search cannot.
- Added `schemas/atlas-findings-block.v1.json` for what a producer supplies.
  It has no `verdict`, `verification_method` or `finding_id` — those are
  assigned by whatever checked the finding — and the parser now enforces that
  closed key set, so a smuggled `verdict` refuses the block instead of being
  silently dropped.
- `atlas-evaluation.v1` also gains the `claim_text_mismatch` gap code, for a
  finding whose prose says something other than its typed claim. The retry
  feedback hands back the expected sentence verbatim, since derived text is
  not guessable.
- `atlas-evaluation.v1` gains `verification_method` and `claim_check` on each
  `citation_checks` entry, plus `contradicted_findings` and
  `unverified_findings` gap codes. Both gaps are actionable: a refuted finding
  can be corrected or dropped, and a missing condition can be declared.

Roadmap P0.2: the evidence filter is wired into the run.

- `AtlasController.run` takes `evidence: EvidenceBase | None` beside the
  existing `observations: list[str]`. They are separate channels for separate
  things — prose context an adapter formatted, and sources that can be re-read
  and re-hashed — and there is **no conversion** between them. Building an
  `Observation` from a formatted string would have to invent a digest, a line
  range and a snapshot, producing a source that claims to be verifiable while
  nothing behind it was read.
- A run without an evidence base is graded exactly as in 1.0. The difference is
  readable rather than implied: `evidence_base` is `null` in the run document
  and `citation_checks` is empty, so nobody has to infer which grading ran.
- The `repo_review` evaluator runs `check_finding()` per structured finding.
  An unknown `source_id`, a tampered excerpt, a file that changed, a missing
  observation, an unreadable findings block, and a finding with no
  machine-readable citation at all can none of them contribute to `passed` —
  each has a test through `AtlasController`, not only through the evaluator.
- Before this, a false claim citing a genuinely-read README passed at 0.9 with
  `evidence_coverage: 1.0`, because the old check asked only whether the
  filename appeared in the finding's text. `test_the_older_checks_would_have_
  accepted_the_same_answer` keeps that fact visible rather than deleting it.
- **A sound citation still does not mean `verified`.** It means the claim is
  *eligible* for a semantic check that does not exist yet, so a false claim with
  a correctly quoted source still passes the gate. A test asserts this, so a
  green run is not mistaken for a verified one. P0.2's boxes stay open.
- Retry feedback names the failing citation and its status instead of repeating
  the gap code. A gap a re-quote could close earns another pass; one needing a
  fresh observation (`stale_source`, `excerpt_mismatch`, `path_refused`,
  `unsupported_source_type`) stops instead of burning an iteration.
- `EvidenceBase` refuses observations from another snapshot and duplicate
  `source_id`s, validated in `__post_init__` so `dataclasses.replace` cannot
  step around it.
- Schemas: `atlas-run.v1` gains optional `evidence_base`; `atlas-evaluation.v1`
  gains optional `citation_checks` and three additive `evidence_gaps` codes
  (`malformed_findings`, `uncheckable_findings`, `unsound_citations`).
  Documents written against the earlier code set still validate.
- The run document exports `evidence_manifest` — a sanitised
  `atlas-observation-manifest.v1` — and never the evidence base. `asdict` had
  been walking straight into the base and publishing every excerpt the run read
  plus the absolute path it read from; the sanitised manifest from P0.1c
  existed and was not being used. `snapshot.root` is dropped rather than
  masked, because redaction recognises home directories and credential shapes,
  not an arbitrary absolute path such as one under `/private/var`. The prose
  `observations` channel is still exported verbatim, as in 1.0, and a test
  asserts that so the sanitised manifest does not imply the whole document is
  safe.
- One gap that needs a fresh observation now blocks the retry for the whole
  output. A retry re-runs the producer once, so a pass that fixed the citable
  findings would still return the stale one unchanged and spend an iteration
  failing on the same ground. The earlier rule returned "actionable" as soon as
  any finding lacked a citation, without looking at what the other findings
  required. The run now also records why it did not try again, since "the loop
  gave up" and "observe the sources again" call for different actions.
- Known at the time and since fixed: a run that exhausted its iterations on an
  evidence gap reported `no_actionable_retry` rather than `max_iterations`,
  because that choice keyed off `missing_sections`. Closed by P0.3 box one,
  above.

Roadmap P0.2a: `Finding.v1` and deterministic verification.

- Added `atlas_core/finding.py` and `schemas/atlas-finding.v1.json`: a claim,
  its scope, a severity that must carry a rationale, the citations it rests on,
  the verification method, the verdict, limitations and a reproducible command.
- **`check_finding()` cannot return `verified` or `contradicted`.** A citation
  being unusable — unknown id, wrong digest, a quote that is not where it
  claims — says the pointer is broken, not that the claim is false. Both an
  unusable citation and an intact-but-unchecked claim return
  `insufficient_evidence`; `citations_are_sound()` carries the discrimination
  so the verdict does not have to. `contradicted` is reserved for a claim a
  semantic check has actually disproved.
- Only `local_file` observations are checked. A `github_file`, `ci` or `memory`
  source returns `unsupported_source_type` rather than being read off a local
  path that happens to match, which would confirm the wrong artifact.
- A test greps the module to assert that no code path constructs `verified`
  or `contradicted`, so the guarantee above is structural rather than a
  convention someone has to remember.
- A finding is built `insufficient_evidence` with method `none`. A verdict is
  attached by a checker via `EvidenceCheck.apply_to`, and a producer that
  writes `verdict="verified"` onto its own finding is overruled rather than
  believed.
- `EvidenceRef` carries what the finding *claims* about a source, checked
  against the run's observations rather than copied from them — copying would
  make every citation trivially correct.
- Negative coverage: unknown `source_id`, wrong digest, wrong line range,
  cherry-picked quote, range past end of file, empty evidence, stale source,
  deleted source, and one bad reference among several.
- A citation is checked with **one** read. Confirming freshness and then
  reopening the file for the quote left a window in which the file could change
  between them, so the digest would describe content the quote was never
  compared against. A test counts the reads.
- Containment is checked at that read. `Observation.path` is a plain string and
  accepts `../` and absolute forms, and the collection wrapper in `integrity`
  does not cover a later re-read, so an escaping path now returns
  `path_refused` rather than being followed.
- A citation is checked against the run's **observation**, not against the file
  alone. Three things must agree, all from the bytes of that single read: the
  digest still describes the file, the observation's own excerpt still matches
  the line range it claims (`excerpt_mismatch`), and the finding's quote sits
  inside the range the observation recorded (`quote_outside_excerpt`). Folding
  two reads into one had dropped the excerpt check `verify_observation` was
  doing, and without the range check a finding could quote a later part of the
  file perfectly while no observation covered those lines — an accurate
  citation standing in for an observation that was never made.
- Added `integrity.read_within`, and the checker reads through it. `O_NOFOLLOW`
  moves the containment refusal into the operation that creates the descriptor,
  so a file replaced by a symlink *after* its name was checked is refused
  instead of served. A test performs that swap inside the window and asserts
  both the refusal and that the unprotected read would have returned bytes from
  outside the root. A directory component swapped in the same window is still
  open, and is stated as such in the module's threat model.
- Semantic verification is not here. Deciding whether an intact source supports
  a claim is P0.2b.

Roadmap P0.1a: `Observation.v1`.

- Added `atlas_core/observation.py` and `schemas/atlas-observation.v1.json`:
  provenance for one thing that was read — `source_id`, source type, path,
  collection time, content hash, excerpt with line range, repo/ref/commit or
  snapshot id, worktree state and confidentiality class.
- A field that cannot be verified carries the literal `"unknown"`. Blank and
  whitespace are rejected, so an absent value cannot be smuggled in looking
  like a present one, and a malformed digest is refused rather than stored.
- `commit` and content identity are kept apart. A dirty worktree serves
  different bytes from the same path, so `commit_identifies_content()` is true
  only for a clean worktree, and `content_sha256` — taken over the full content
  read, never over the excerpt — stays authoritative on its own.
- Validation lives in `__post_init__`, so `dataclasses.replace` cannot write a
  malformed digest or a blank commit into an already-validated object.
  `source_id` is re-derived and a mismatch is refused, so an observation cannot
  be re-pointed at a different path while keeping the old id.
- Nothing is wired into the controller. Collection and snapshots are P0.1b.

Roadmap P0.1b: snapshots, collection and drift detection.

- Added `atlas_core/snapshot.py`. `take_snapshot()` establishes commit, ref and
  worktree state from git, and says `unknown` for anything it cannot establish
  rather than guessing. Snapshot ids are derived, so the same unchanged
  checkout is recognisably the same snapshot.
- `collect_observation()` reads one file into an `Observation.v1`, hashing the
  full content and keeping a bounded excerpt with its line range. A missing
  file raises instead of producing an observation with an `unknown` digest.
- `verify_observation()` re-reads a source and returns `fresh`, `stale`,
  `missing` or `unverifiable`. Both the content digest and the quoted line
  range are checked, so an excerpt that no longer matches the lines it claims
  is stale even when the digest would pass.
- `Verification.is_evidence()` is the single place deciding what may back a
  claim, and only `fresh` qualifies.
- `detect_drift()` answers "did HEAD or a file move during the read". It pairs
  the state check with a per-source content check, because `has_moved()` alone
  cannot see an already-dirty worktree changing again.
- Still not wired into the controller; the loop keeps its `list[str]`
  observations.

Roadmap P0.1c: source integrity and safe handling of observation data.

- Added `atlas_core/integrity.py`. `resolve_within()` refuses absolute paths,
  `..` escapes, a sibling directory sharing a prefix, and symlinks pointing out
  of the snapshot. A symlink that stays inside is allowed — the rule is about
  where bytes come from, not about links. Refusal, not clamping: reading a
  different file than the one requested is worse than failing.
- `redact_text()` masks credential formats, home directories and email
  addresses. Deliberately narrow, so hex digests, commit ids, versions and
  in-repo paths survive — masking the context needed to check a claim would
  defeat the point. Verified against this repo's own files: no false positives.
- `redacted_manifest()` is the exportable record: masked excerpts, snapshot
  provenance, and per-entry verification status. It keeps `content_sha256`
  unmasked so the manifest still points at what was verified, and omits
  `snapshot.root`, which is an absolute path naming a user and a machine. An
  entry built without re-verification reports `unknown`, never `is_evidence`.
- Redaction is a view, not storage. Collected excerpts stay raw, because
  verification compares the excerpt against the lines it claims — masking at
  collection made an untouched source verify as `stale`, which a test caught.
- Masking covers the **whole** export, not only the excerpt. A path like
  `docs/privat@example.com.md` or a token-shaped branch name leaves a run
  through metadata as readily as through content, so every exported string is
  masked except the verification pointer — `content_sha256`, the ids and the
  structural enums. The digest stays verbatim because a masked digest points
  at nothing.
- A private key is masked as a whole block. Matching only the `BEGIN` header
  left the key body and `END` line in the clear; an unterminated block now has
  its base64 run masked too, while following prose survives.
- `collect_observation_safely()` reads through the **resolved** path instead of
  the string it was asked for, so a symlink inside the root cannot be repointed
  between the check and the read. The recorded path is the concrete file.
- Documented what containment does **not** cover: `verify_observation()` has no
  check of its own, `Observation.path` still accepts `../` and absolute forms,
  and redaction is best-effort against arbitrary personal data. The full P0.1
  security box stays open.
- Negative tests cover tampering that preserves length, trailing-whitespace
  edits, a commit that does not make a changed file fresh again, path
  traversal, symlink escape, secret leakage into the manifest, secrets in
  `path`/`repo`/`ref` metadata, and a full PEM block.
- `ROADMAP.md` P0.1 status updated. Only the `Observation.v1` box is ticked;
  the other three stay open with what each PR covers and what remains.

Terminal states are now legible to callers.

- A model adapter that raises, or returns anything other than a `ModelResult`
  with non-empty output, ends the run as `failed` / `failed` instead of
  propagating an unhandled exception. The stage and exception type are recorded
  under `metadata.failure`, with the provider message truncated to 512
  characters.
- A failing adapter does **not** fall back to the rule-based executor. Serving
  a deterministic template as though a model produced it would be a false
  success. The rule-based default still applies when no adapter is configured.
- **Behaviour change:** `atlas run` no longer exits `0` for every terminal
  state. 0 passed, 1 failed, 2 finished without passing
  (`no_actionable_retry`, `max_iterations`), 3 approval required. A test
  asserts every declared stop reason has a code, so adding one forces the
  decision.
- The text output is now rendered from the run document by `render_run_text`,
  so text and `--json` cannot drift. It also surfaces evidence gaps and the
  failing stage in the trailer.
- Added `StubModelAdapter`, exported from the package root: drives the model
  path deterministically in CI with no provider or API key.
- Documented that timeouts are the adapter's responsibility. `execute()` is
  synchronous and the core cannot cancel one in progress, so it does not
  pretend to impose a deadline.

Roadmap phase P1: the evaluator grades evidence, not formatting.

- Added a per-route evaluator contract (`RouteEvaluator`). Routes without one
  are graded on formatting exactly as before; `repo_review` is the first route
  that must also show its sources.
- `AtlasEvaluation` gained `evidence_gaps`, `unverified_claims` and
  `evidence_coverage`, declared as optional fields in `atlas-evaluation.v1`.
  They are deliberately separate from `missing_sections`: a heading being
  present says nothing about whether the claim under it is supported.
- Evidence now moves `quality_score`, so the gate is arithmetic rather than a
  boolean override. A `repo_review` that cites nothing scores 0.71 against a
  0.78 threshold.
- **Behaviour change:** `repo_review` with no observed sources no longer
  passes. It stops at one iteration with `no_actionable_retry`, because no
  further pass over an empty observation list could cite anything.
- A retry can now close an evidence gap: the executor emits `## Observed
  sources` recording the sources it actually held, and moves claims it could
  not tie to one into `## Unverified claims`. The section is named for what it
  proves — that the files were read — not for a verification it does not
  perform.
- The evidence check is citation, not verification. A finding counts as
  supported when it names a source that was read; nothing compares the claim
  against that source's contents. A wrong statement mentioning `README.md`
  still passes.
- Renamed the static `repo_review` heading `## Key findings` to
  `## Review method`. Those three bullets describe how to assess a repo; they
  were never findings about one.
- `tests/test_evidence_evaluator.py` covers the P1 Definition of Done and adds
  the end-to-end second-iteration test the loop never had: a run that scores
  0.71, names an actionable gap, and reaches 0.95 on the second pass with new
  evidence.

## v1.0.0 — 2026-09-19

First stable release. Makes the engine do what the README describes.

- Retry is now a replan: the previous evaluation is passed into the executor,
  which closes the specific sections the evaluator named as missing. The
  unconditional "Loop improvement" note that claimed an improvement no
  iteration had made is gone.
- Evaluation retries only when a gap is actionable. A deterministic rerun with
  identical input no longer burns an iteration.
- `repo_review` and `learning` now emit the `Recommendation` and `Next step`
  sections the evaluator grades them on; `root_cause` gained `Next step`. Every
  shipped route can now pass its own quality gate on the first iteration.
- Observations reach every route, not just `repo_review`, and are rendered under
  `## Sources inspected`.
- `AtlasEvaluation` gained `missing_sections`: machine-readable gap codes shared
  by the evaluator and the executor.
- `--json` output carries `"schema": "atlas-run.v1"`, and `schemas/` now
  describes the documents the engine actually emits. `tests/test_schemas.py`
  checks them against each other.
- The write-action notice moved from the observation list to
  `metadata.safety_notice`; a warning is not a source.
- `AtlasController.run` no longer appends to the caller's `observations` list.
- `docs/safety-model.md` now states where the read-only boundary is enforced and
  where it is only advisory, as the README claims it does.
- Added the v0.3 model adapter scaffold: optional `ModelAdapter`,
  provider-neutral `ModelResult`, rule-based fallback, and tests for model
  output plus write-approval gating.
- Added the v0.4 mqobsidian adapter scaffold: bounded compact-context reads,
  explicit durable-memory labelling, candidate-only writes, and optional
  controller/CLI integration without an MQ package dependency.
- Added the v0.5 ChatGPT Skill package generator with live route summaries,
  CLI examples, safety boundaries, overwrite protection, and drift tests for
  the checked-in integration package.
- Stabilized the v1.0 loop API with public type exports, explicit stop reasons,
  positive iteration bounds, closed versioned schemas, and a documented 1.x
  adapter and write-boundary contract.

## v0.2.0 — 2026-07-31

Adds repo observation support and GitHub Actions runner.

- CLI flags: `--repo`, `--repo-ref`, `--repo-path`
- `GitHubRepoAdapter` using GitHub REST API
- `FilesystemRepoAdapter` for local repo context
- `run-atlas.yml` workflow_dispatch runner
- GitHub reader adapter docs

## v0.1.0 — 2026-07-31

Initial standalone Atlas Core MVP.
