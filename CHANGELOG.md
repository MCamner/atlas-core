# Changelog

## Unreleased

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
- **`check_finding()` cannot return `verified`.** It establishes that a
  citation is sound — the source was read in this run, the claimed digest
  matches, and the quoted text sits contiguously at the line range it names —
  and none of that shows the source supports the claim. Sound citations earn
  `insufficient_evidence`; broken ones earn `contradicted`. A test greps the
  module to assert no code path constructs `verified`.
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
