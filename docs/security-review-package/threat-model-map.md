# Threat Model Map

Code security baseline: `6474f17d4ca6fa75d56f29d2475ad4bfcb1c7d60`

Each area lists what the authors say is enforced, where it is implemented,
which tests exercise it, and which limits are already documented. "Enforced"
here is the authors' claim, to be checked by the reviewer, not a conclusion.

The last section lists questions the authors want an independent answer to.
They are not findings and carry no severity.

## 1. Prompt injection

| | |
| --- | --- |
| Claim | Repository and tool output are data. Model text cannot register a tool, raise its capabilities or approve a write. |
| Code | `atlas_core/tool_gateway.py` (`ToolGateway.invoke`, `invoke_write`), `atlas_core/adapters/live_model.py` (`LiveModelAdapter.capabilities`, `invoke_tool`), `atlas_core/approval.py` |
| Tests | `tests/test_p03_attack_matrix.py` (`test_real_readme_prompt_injection_cannot_authorize_write_tool`, `test_tool_output_is_data_not_an_instruction_to_invoke_write`), `tests/test_tool_gateway.py` (`test_readme_instruction_is_only_data`), `tests/test_model_capabilities.py`, `tests/test_approval.py` (`test_invoke_never_runs_a_write_tool_even_with_a_valid_token`) |
| Documented limit | Core does not guarantee an external model ignores malicious text (`docs/safety-model.md`, "Text is not evidence"). |

## 2. Supply chain

| | |
| --- | --- |
| Claim | No runtime dependencies. CI and build dependencies exact-pinned and hash-locked. Actions pinned by full SHA. Vulnerability audit gates CI. |
| Code / config | `pyproject.toml` (`dependencies = []`, `ci` and `build` groups), `uv.lock`, `.github/workflows/*.yml`, `.github/dependabot.yml` (uv and github-actions, weekly), `scripts/reproducible_build.py` (build group must match PEP 517 requirements) |
| CI steps | `uv lock --check`, `uv sync --locked`, `pip-audit --strict` in `.github/workflows/test.yml` |
| Tests | `tests/test_reproducible_build.py`, `tests/test_release_metadata.py` |
| Documented limit | Dependabot security updates are disabled on the repository (version updates are configured). Dependabot PRs have no required approval. See [`hosting-controls.md`](hosting-controls.md). |

## 3. Secrets

| | |
| --- | --- |
| Claim | Provider keys stay out of run documents. Exports are redacted. CI scans tracked files for secrets and proves the scan rejects a synthetic key. |
| Code | `atlas_core/redaction.py` (`SECRET_PATTERNS` including `sk-proj-`-style, `AIza`, AWS secret and `Bearer` shapes since #105, `HOME_PATH`, `EMAIL`, `VERBATIM_KEYS`), `atlas_core/integrity.py`, `atlas_core/adapters/live_model.py` (`ProviderConfig.api_key` with `repr=False`, `describe()`, `config_id`), `atlas_core/patch_proposal.py` (test output passed through `redact_text`) |
| CI | `detect-secrets-hook` against `.secrets.baseline` (34 entries, all classified as false positives in `docs/security-review.md`); `scripts/secret_scan_smoke.py` canary |
| Tests | `tests/test_redaction.py` (incl. `TestCommonKeyShapes`), `tests/test_integrity.py`, `tests/test_live_provider.py`, `tests/test_approval.py` (`test_the_token_is_never_written_down`) |
| Documented limit | Redaction matches credential shapes, home directories and email addresses only. A wrongly approved baseline entry can hide a real secret. |

## 4. Path traversal and TOCTOU

| | |
| --- | --- |
| Claim | Reads are refused, not sanitised, when a path escapes the snapshot root. Symlinks are resolved before the check. The final component is opened with `O_NOFOLLOW`. |
| Code | `atlas_core/containment.py` (`resolve_within`, `read_within`), `atlas_core/snapshot.py` (`GIT_HARDENING`: git runs with `-c core.fsmonitor=false`, #100), `atlas_core/observation.py` (path refused at construction), `atlas_core/finding.py` (`LocalFileReader`), `atlas_core/patch_proposal.py` (`_safe_path`, `patch_paths`, refused symlink/submodule modes) |
| Tests | `tests/test_snapshot.py` (`test_the_repositorys_own_config_cannot_run_a_command`), `tests/test_integrity.py` (`test_a_symlink_pointing_outside_is_refused`, `test_a_symlinked_directory_pointing_outside_is_refused`, `test_the_unprotected_read_would_have_served_the_outside_bytes`), `tests/test_observation.py`, `tests/test_finding.py`, `tests/test_redaction.py`, `tests/test_adapters.py`, `tests/test_patch_proposal.py` (`test_paths_outside_the_repository`, `test_symlinks_and_submodules`, `test_a_path_through_an_existing_symlink`) |
| Documented limit | A directory component can still be swapped for a link between resolve and open (`atlas_core/integrity.py` module docstring). |

## 5. SSRF and network access

| | |
| --- | --- |
| Claim | Core has no generic URL tool. The GitHub reader targets `https://api.github.com` only. The tool gateway denies `network` capability. |
| Code | `atlas_core/adapters/github_reader.py` (`owner/name` regex with `.`/`..` refused since #106, `quote(ref, safe="")`, per-GET budget, bounded body, timeout ≤ 15 s), `atlas_core/adapters/live_model.py` (`UrllibTransport`, reply bounded to 16 MiB since #104, endpoint from config or `ATLAS_MODEL_ENDPOINT`), `atlas_core/adapters/_http.py` (drops `Authorization` on cross-origin redirects, #102), `atlas_core/tool_gateway.py` |
| Tests | `tests/test_tool_gateway.py` (`test_read_only_denies_write_and_network_before_handler`), `tests/test_redirect_credentials.py`, `tests/test_provider_response_bound.py`, `tests/test_adapters.py`, `tests/test_live_provider.py` |
| Documented limit | Trusted custom adapters run with host privileges and can open any connection. |

## 6. Privileged writes

| | |
| --- | --- |
| Claim | `atlas run` is read-only. The only write path is `ToolGateway.invoke_write` with a single-use token bound to an exact `Operation` (tool, arguments, repo, ref, clean commit). `atlas propose` creates one `refs/heads/atlas/<name>` by compare-and-swap, verifies it, and rolls back by compare-and-swap. |
| Code | `atlas_core/approval.py` (`Operation`, `ApprovalAuthority`, `clean_head`), `atlas_core/tool_gateway.py` (`invoke_write`), `atlas_core/patch_proposal.py` (`prepare`, `_create_branch`, `verify_created`, `rollback`, `validate_branch`, `_printable` for the approval screen since #101) |
| Tests | `tests/test_approval.py` (26 tests: exact write once, concurrent token use, expiry on two clocks, HEAD moved, argument mutation, no retry), `tests/test_patch_proposal.py` (incl. `test_control_characters_are_shown_not_interpreted`) |
| Documented limit | The approval proves that whoever controls the terminal saw the operation, not that a person approved (F4, open; see [`pre-review-findings.md`](pre-review-findings.md#f4--terminal-approval-does-not-prove-a-human-approver)). The `--test` command runs as the caller, without a sandbox. `clean_head` checks HEAD and worktree, not where `ref` points; the use case must make the base a precondition of the mutation (done in `atlas propose` with `update-ref --stdin` `verify` + `create`). |

## 7. Process isolation and resource limits

| | |
| --- | --- |
| Claim | Public `atlas run` on POSIX runs a worker in its own session; the parent enforces wall time and output caps and kills the process group. `run_isolated` does the same for trusted Python callbacks. Windows fails closed. |
| Code | `atlas_core/process_guard.py`, `atlas_core/isolation.py`, `atlas_core/worker_cli.py`, `atlas_core/budget.py`, `atlas_core/host_api.py` (locks, `LockUnavailable`) |
| Tests | `tests/test_p03_bounded_cli.py`, `tests/test_p03_hard_cli.py`, `tests/test_p03_isolation.py`, `tests/test_p03_controller.py`, `tests/test_budget_concurrency.py`, `tests/test_platform_locks.py` |
| Documented limit | A process is not a security sandbox. In-process API and `--unsafe-legacy-unbounded` are cooperative or unbounded. |

## 8. Exfiltration through output

| | |
| --- | --- |
| Claim | Observations and output are bounded; the exported run document is redacted. |
| Code | `atlas_core/budget.py`, `atlas_core/adapters/live_model.py` (`PromptLimits`), `atlas_core/redaction.py`, `atlas_core/integrity.py` |
| Tests | `tests/test_prompt_bounds.py`, `tests/test_partial_reads.py`, `tests/test_redaction.py` |
| Documented limit | A model may repeat sensitive source content; redaction is not comprehensive. When a live model is configured, observed repository content is sent to that endpoint. |

## 9. CI and release integrity

Covered in [`release-integrity.md`](release-integrity.md) and
[`hosting-controls.md`](hosting-controls.md). Workflows request
`contents: read` (Pages additionally `pages: write`, `id-token: write`).
`run-atlas.yml` passes `workflow_dispatch` inputs through `env` rather than
expression interpolation.

## Questions for the reviewer

The authors cannot give an independent answer to these. No severity is
implied. Questions 1, 3 and 4 from the first version of this package were
addressed by fixes (O1, F3, F5 in [`pre-review-findings.md`](pre-review-findings.md));
they stay listed so the reviewer can check the fixes.

1. **GitHub `owner/name` pattern** (fixed in #106). Is refusing `.`/`..`
   segments sufficient?
2. **Live model endpoint.** `ATLAS_MODEL_ENDPOINT` (or host config) accepts any
   URL, including `http://`. The API key and bounded prompt are sent there.
   `docs/safety-model.md` argues environment variables are closer to
   repository content than to the host for capabilities. Does the same
   argument apply to the endpoint and key? (The public CLI does not build a
   live model adapter; this concerns hosts calling `build_model_adapter()`.)
3. **Redirects** (fixed in #102). Is dropping only `Authorization` on a
   scheme, host or port change sufficient?
4. **Provider response size** (fixed in #104). Is 16 MiB an appropriate bound?
5. **Caller-supplied paths.** Event log, lock, cancel, feedback store and
   `generate-skill --force` paths come from the caller. Is the "caller is
   trusted" assumption stated clearly enough for hosts that pass through
   user input?
6. **Directory-component TOCTOU.** Is the documented residual window
   acceptable for the read-only use case as deployed?
7. **Git configuration beyond `core.fsmonitor`.** Is overriding only
   `core.fsmonitor` sufficient for the observed repository, and is the
   remaining exposure in `atlas propose` (textconv, `reference-transaction`
   hook in the caller's own repository) acceptable?
8. **F4.** Does terminal approval, as documented, satisfy the exit condition
   "no autonomous mutation without permission"?
