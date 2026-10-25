# Threat Model Delta since `v1.0.0`

Pinned release SHA: `83d7d2c12ddaf00454be2adfcb9ceb3a6223552d`

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
| Verified by the authors | `GIT_HARDENING` (`core.fsmonitor=false`) and `containment.py` are unchanged since `v1.0.0` (`git diff v1.0.0 83d7d2c -- atlas_core/containment.py` is empty, and the `snapshot.py` diff touches only windowing) |

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
| Verified by the authors | `git diff v1.0.0 83d7d2c -- schemas/atlas-findings-block.v1.json atlas_core/adapters/output_contract.py` is empty |
| Known risk | A v1 reader skips a v2 block and therefore does not see the relation finding. This is deliberate, and it is not full functional backward compatibility |

For the reviewer:

6. Test the boundary explicitly. Does a v1 reader skip a v2 block? Is a relation in a v1 block refused? Can the model path state the relation by any route, including a provider that ignores the schema? (The reply is still parsed locally by `structured_findings`, and `output_contract.py` wraps model findings in the v1 fence.)
7. `structured_findings` takes the first block of either fence. What happens when an output holds both a v1 and a v2 block, and who could cause that?

## 5. Repository text can reach the findings parser

This was **reproduced by the authors**. It is **present at `v1.0.0` too**, so it was not introduced in this release.

Observations are rendered into the route output under `## Sources inspected` as `- <path>:\n<content>`. Only the first line gets the prefix, so a line in an observed file that starts with ```` ```atlas-findings ```` appears at the start of a line in the output, and `structured_findings` matches it.

The authors' probe is a throwaway repository whose `README.md` contains an empty ```` ```atlas-findings ```` block. For the task "Granska repot och dess README", the `documentation` topic parsed that block as present with 0 entries, at both `83d7d2c` and `v1.0.0`, and the run stopped at `max_iterations`. For the `release_metadata` topic, which does not read `README.md`, the producer's own block was the only one. The commands are in [`review-commands.md`](review-commands.md#repository-text-in-the-findings-parser).

The authors have not shown that this can produce a wrong PASS. A verified citation needs the cited `source_id` and `content_sha256`. The `source_id` derives from the snapshot (root path, commit, worktree state), and the commit depends on the file that would contain the block. That limits the risk, but it has not been tested further.

For the reviewer:

8. Is this a finding, and how severe is it? Can injected repository text make a finding verify, satisfy a criterion such as structured output being present, or displace the producer's block? Is it blocking for v1.1.0 even though `v1.0.0` already had it?

## 6. Supply chain and CI

| | |
| --- | --- |
| Claim | Actions are pinned by full SHA. CI and build dependencies are exact-pinned and hash-locked. The audit now covers every locked group, exported with hashes and without the project (#146). Release artifacts are built twice and must match. |
| Code / config | `.github/workflows/test.yml`, `run-atlas.yml`, `pyproject.toml`, `uv.lock`, `scripts/reproducible_build.py` |
| Verified by the authors | The release bundle from exact-main run 40217200863 matches its manifest. A local rebuild at the target on macOS reproduces the wheel and sdist digests byte for byte ([`evidence.md`](evidence.md#release-bundle)) |
| Known risk | PyPI's `atlas-core` is an unrelated project. The CI E2E checks out a second repository, and the release bundle is built later in the same job |

For the reviewer:

9. In the same `python` job, CI runs `atlas run` over the mq-agent checkout at pinned commit `aa7411d…`, with `persist-credentials: false` and `contents: read`. It then deletes the checkout and later builds and uploads the release-integrity bundle. Is that ordering acceptable, or should the release build run in a job that never processes another repository's content?
10. Does the `uv export … --all-groups --no-emit-project` audit miss anything the environment audit covered? Is the PyPI name collision a release blocker, or does the statement in the release notes ("not published on PyPI") suffice?
11. `upload-artifact` 7.0.2 (#132) uploads the bundle. Box 6 has to show that the bundle can be retrieved and matches. Is anything else in the new major version relevant?

## 7. Routing (#112)

The claim is that the product name `atlas` no longer selects `prompt_improvement`, and that the remaining keywords are unchanged.

12. Does any task now route to a topic with a broader read plan than it did at `v1.0.0`?
