# Threat Model Delta since `v1.0.0`

Pinned release SHA: `7d0d86c3ee88a8b2c62938d36d9fc77ae6fcfd58`

The `v1.0.0` threat model (`../security-review-package/threat-model-map.md`)
still describes the unchanged areas: prompt injection into tools and approval,
secrets, path containment, SSRF, privileged writes, and process isolation. This
file covers only what changed. For each area it gives the claim, the code, the
tests, what the authors verified, and the questions for the reviewer. A claim
here is the authors' claim, not a conclusion.

## 1. Deterministic producers can make a run pass without a model

| | |
| --- | --- |
| Claim | A producer emits typed findings computed from observed text. The evaluator re-checks every citation and every typed claim against the observations, so a producer cannot verify a claim the observed lines do not support. A producer declines, which means it emits nothing, when it cannot read everything its verdict depends on. |
| Code | `atlas_core/review_producers.py` (`_produce_ci_release_gate_parity`, `_produce_ci_test_command_parity`, `_produce_release_changelog_parity`, `_produce_release_metadata_parity`, `_PRODUCERS`). The topics are defined in `atlas_core/review_plan.py`, and the producers are invoked from `atlas_core/executor.py` and `controller.py` |
| Tests | `tests/test_deterministic_ci_review.py`, `tests/test_deterministic_release_review.py`, `tests/test_deterministic_gate_parity_review.py`, `tests/test_targeted_line_ranges.py`, `tests/test_producers_decline_on_partial_reads.py` |
| Verified by the authors | At the target, `atlas run --repo-path .` passes `release_metadata` and `release_changelog` on iteration 1, with every citation `verified` against 1.1.0. CI runs the gate-parity loop against the pinned mq-agent, plus a negative variant in which the relation must verify ([`evidence.md`](evidence.md)) |
| Known risk | The producers parse shell and YAML lines with line-based rules, not a parser. Whether a producer engages depends on keywords in the task (for example `samma`, `match`, `synk`). A task worded otherwise stops without passing. It is not shown to pass wrongly |

For the reviewer:

1. Can a repository be shaped so that a producer emits a finding that *verifies* while the conclusion text is wrong? A finding's claim is derived from its typed claim, but the producer writes the conclusion sentence above the block.
2. Do the decline rules in #129 and #134 cover every case where a partial read could change the verdict? Look at the 200-line exact-path excerpt from #127, and at sources longer than the window.

## 2. Observation windows

| | |
| --- | --- |
| Claim | A window can start at an explicit line or at the first line that begins with a bounded static `anchor_prefix` (one line, at most 128 characters, no regex). It can never export more than the 80-line bound, and it targets only paths the review plan already selected. The full file is read through `read_within` as before, and its SHA-256 remains the content identity. A new excerpt of unchanged bytes is `reframed`, and a content change is still `superseded`. |
| Code | `atlas_core/snapshot.py` (`collect_observation`, `_first_prefixed_line`, `_excerpt`), `atlas_core/observer.py` (`LineWindow`), `atlas_core/adapters/filesystem_repo.py` (`EXACT_PATTERN_MAX_LINES = 200` for `GATE_PARITY_PATHS`, window handling), `atlas_core/controller.py` (round merging) |
| Tests | `tests/test_targeted_line_ranges.py`, `tests/test_eventlog.py`, `tests/test_repo_path_evidence.py`, `tests/test_plan_reaches_its_subject.py` |
| Verified by the authors | `GIT_HARDENING` (`core.fsmonitor=false`) and `containment.py` are unchanged since `v1.0.0` (`git diff v1.0.0 7d0d86c -- atlas_core/containment.py` is empty, and the `snapshot.py` diff touches only windowing) |

For the reviewer:

3. In `FilesystemRepoObserver`, #119 replaced the per-round dedupe on `source_id` (commented "Two names for one file … a round may carry each source once") with a dedupe on the requested path. `source_id` is derived from the requested relative path (`observation.derive_source_id`). Can one round now carry two observations with the same `source_id`, for example through path spelling variants? Does that matter to the merge and drift logic?
4. When a window range fails with `ValueError`, the observer falls back to re-reading the head of the file, on the reasoning that the file changed during the run. Can that fallback be triggered without a change, and does it hide anything?

## 3. The `command_targets_differ` relation claim

| | |
| --- | --- |
| Claim | The check re-derives both target sets from the exact cited command lines and requires them to equal the declared sets and to differ from each other. It also requires the claim sentence to be exactly the rendered form. |
| Code | `atlas_core/claim_check.py` (`_check_command_targets_differ`, `_targets_from_cited_command`, `_quote_names_command`, `_command_targets`) |
| Tests | `tests/test_claim_check.py`, `tests/test_deterministic_gate_parity_review.py`, and the negative E2E in `test.yml` |

For the reviewer:

5. The target sets are derived from `reference.quoted`, the citation text that the finding supplies. The check holds only if citation soundness has already established that each `quoted` string appears at the cited lines of an observation with the cited digest. Confirm the order: is a `command_targets_differ` claim ever settled on a citation that has not passed that check?

## 4. The findings block: v1 and v2 (#128, #148)

| | |
| --- | --- |
| Claim | `atlas-findings-block.v1` is the `v1.0.0` shape. `command_targets_differ` exists only in `atlas-findings-block.v2`, carried in a ```` ```atlas-findings.v2 ```` fence that the `v1.0.0` reader pattern does not match. A v1 block that contains the relation is refused as malformed. The model output schema is the `v1.0.0` schema, so a model is offered only the literal kinds. |
| Code | `atlas_core/evidence.py` (`FINDINGS_FENCE`, `FINDINGS_FENCE_V2`, `_FINDINGS_BLOCK`, `structured_findings`), `atlas_core/review_producers.py` (`_render`, `_is_relation`), `atlas_core/adapters/output_contract.py`, `schemas/atlas-findings-block.v1.json`, `schemas/atlas-findings-block.v2.json` |
| Tests | `tests/test_findings_block_versions.py`, `tests/test_structured_output.py` (`TestTheSchemaMatchesTheRepositorysContract`), `tests/test_deterministic_gate_parity_review.py` |
| Verified by the authors | `git diff v1.0.0 7d0d86c -- schemas/atlas-findings-block.v1.json` is empty. `output_contract.py` changed in #151 (`findings_block`, `render_findings_block`), but `output_schema()` and `_FINDING_ITEM` at the target equal those at `v1.0.0`, compared as values |
| Known risk | A v1 reader skips a v2 block and therefore does not see the relation finding. This is deliberate, and it is not full functional backward compatibility |

For the reviewer:

6. Test the boundary explicitly. Does a v1 reader skip a v2 block? Is a relation in a v1 block refused? Can the model path state the relation by any route, including a provider that ignores the schema? (The reply is still parsed locally by `structured_findings`, and `output_contract.py` wraps model findings in the v1 fence.)
7. `structured_findings` takes the first block of either fence. What happens when an output holds both a v1 and a v2 block, and who could cause that?

## 5. SEC-01: repository text and the findings channel

This was **found by the authors** in the preparatory work for this review, and
it is fixed in #151. It is GHSA-m8fx-mmrx-c449, and it affects `v1.0.0`.

**What was wrong.** `structured_findings` took the first findings fence in the
whole route output. The rule-based executor appends observed file content to
that output under `## Sources inspected`, and the content is rendered so that a
fence line in a file starts a line in the output. In a directory where git
cannot resolve a commit, `snapshot_id` is `sha256(root, "unknown", "unknown")`.
The cited `source_id` and `content_sha256` are then predictable from the
absolute root path and the file content. The authors reproduced this at
`83d7d2c` and at `v1.0.0`. A `README.md` block that cited `docs/install.md`
turned a `documentation` review that otherwise stops at `max_iterations` into
`passed` on iteration 1, with one verified finding written by the repository.
In a committed git repository the citation was unsound, because the block
changes its own commit. A producer's block precedes the sources, so producer
findings were not displaced.

The regression tests found a second case. On the model path, `render_output`
puts the model's `report` before the block rendered from `findings`, so a fence
in the report took the place of the model's own findings.

| | |
| --- | --- |
| Claim | The evaluator reads findings only from text a producer wrote. In the rule-based path, that text is the producer's section. On the model path, it is `ModelResult.findings_block` when the adapter sets it. `LiveModelAdapter` sets the block from the reply's `findings`. Once the schema has been sent, a non-conforming reply states no findings. `evaluate()` has no default `findings_source`. |
| Code | `atlas_core/executor.py` (`execute_plan_parts`), `atlas_core/controller.py` (`findings_source`, `metadata.findings_sources`), `atlas_core/evaluator.py` (`evaluate`, `_grade_evidence`, `_grade_against_evidence`), `atlas_core/adapters/model.py` (`ModelResult.findings_block`), `atlas_core/adapters/output_contract.py` (`ReadEnvelope.findings_block`, `render_findings_block`), `atlas_core/adapters/live_model.py` |
| Tests | `tests/test_findings_trust_boundary.py`: the injected finding is sound, so the tests are not vacuous; a directory git cannot describe; a working git repository; git failing to resolve; a v2 fence in observed text; producer precedence; the model's report; a required `findings_source`; the source recorded for each origin; a sent schema as the only channel. Also `tests/test_structured_output.py` |
| Verified by the authors | At `7d0d86c`, the same probe stops at `max_iterations` with no citation checks, and `findings_sources` is `producer_section`. Both gate-parity E2Es pass in CI. Before the merge the fix had a technical review of `3fe0687`. No independent approval is documented |
| Known risk | `adapter_output`. An adapter that does not set `findings_block`, `StubModelAdapter`, and `LiveModelAdapter` with `structured_output=False` all have their whole output read as findings. Atlas adds no observed text to that output, but its prose and findings are one text. It is deprecated for 2.0 and recorded in `metadata.findings_sources` |

For the reviewer:

8. Does #151 close SEC-01? Can any text the run observed still be read as a producer's finding, on any route or adapter?
9. Is the `adapter_output` fallback acceptable for 1.1, given the deprecation, the recorded source and the strict mode after a sent schema? The authors argue that it is outside SEC-01, because Atlas adds no observed text to adapter output. The technical patch review accepted that with documented residual risk.
10. Is the changed behaviour acceptable: a hand-written fence in a reply to a sent schema is no longer read (`tests/test_structured_output.py`, `test_a_handwritten_block_after_a_sent_schema_is_a_missing_block`)?

## 6. Supply chain and CI

| | |
| --- | --- |
| Claim | Actions are pinned by full SHA. CI and build dependencies are exact-pinned and hash-locked. The audit now covers every locked group, exported with hashes and without the project (#146). Release artifacts are built twice and must match. |
| Code / config | `.github/workflows/test.yml`, `run-atlas.yml`, `pyproject.toml`, `uv.lock`, `scripts/reproducible_build.py` |
| Verified by the authors | The release bundle from exact-main run 40217200863 matches its manifest. A local rebuild at the target on macOS reproduces the wheel and sdist digests byte for byte ([`evidence.md`](evidence.md#release-bundle)) |
| Known risk | PyPI's `atlas-core` is an unrelated project. The CI E2E checks out a second repository, and the release bundle is built later in the same job |

For the reviewer:

11. In the same `python` job, CI runs `atlas run` over the mq-agent checkout at pinned commit `aa7411d…`, with `persist-credentials: false` and `contents: read`. It then deletes the checkout and later builds and uploads the release-integrity bundle. Is that ordering acceptable, or should the release build run in a job that never processes another repository's content?
12. Does the `uv export … --all-groups --no-emit-project` audit miss anything the environment audit covered? Is the PyPI name collision a release blocker, or does the statement in the release notes ("not published on PyPI") suffice?
13. `upload-artifact` 7.0.2 (#132) uploads the bundle. Box 6 has to show that the bundle can be retrieved and matches. Is anything else in the new major version relevant?

## 7. Routing (#112)

The claim is that the product name `atlas` no longer selects `prompt_improvement`, and that the remaining keywords are unchanged.

14. Does any task now route to a topic with a broader read plan than it did at `v1.0.0`?
