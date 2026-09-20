# Changelog

## Unreleased

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
  from `claim_check.py`. `finding.py`'s structural guarantee is unchanged, and
  the grep test that enforces it now covers both words.
- The two outcomes are not symmetric, and the module says so. Refutation needs
  one counterexample. A condition that holds shows only that *that condition*
  held — nothing checks it is a fair test of the claim, so a producer that
  declares an easy condition earns an easy `verified`. `verified` therefore
  means "the falsifiable condition this finding named held", and the reasons
  say that rather than presenting the claim as established.
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
- Known and unchanged: a run that exhausts its iterations on an evidence gap
  reports `no_actionable_retry` rather than `max_iterations`, because that
  choice keys off `missing_sections`. Pre-existing, and stop-reason semantics
  belong to P0.3.

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
