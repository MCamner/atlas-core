# Pre-Review Findings

A pre-review was run on 2026-09-27 at `2765e66` (code identical to `07ac394`)
before the independent review. **It was not independent:** it was done by an
AI assistant (Claude, in a Claude Code session) that had taken part in the
implementation and wrote this package. It does not count toward the review
conclusion. It is listed so the reviewer knows what was found, how it was
fixed, and what the authors consider still open.

Each finding was reproduced before it was fixed. Each fix carries a
regression test that failed before the fix and passes after it. "Merge SHA"
is the squash commit on `main`; "main CI" is the `test` workflow `push` run
on exactly that commit.

## Status

| ID | Severity | Status | Finding |
| --- | --- | --- | --- |
| F1 | High | Fixed | Observed repository's git config could run a command |
| F2 | High | Fixed | Approval screen could be altered by terminal control sequences |
| F3 | Medium | Fixed | `Authorization` followed cross-origin redirects |
| F4 | Medium | **Open (design limit)** | Terminal approval does not prove a human approver |
| F5 | Low | Fixed | Provider reply read without a bound |
| F6 | Low | Fixed | Redaction missed common current key formats |
| O1 | Observation | Fixed | GitHub reader accepted `.`/`..` as owner or name |

Severity is the pre-reviewer's. The independent reviewer should reassess it.

## Fixed findings

### F1 — Observed repository could run a command through its git config

- Risk: `take_snapshot` ran `git status` in the observed repository. Git
  honours that repository's `.git/config`, and `core.fsmonitor` names a
  command git runs during `status`. `atlas run --repo-path` (read-only mode)
  ran it; the run still reported `passed`. Precondition: attacker controls the
  `.git` directory on disk (archive, copied or shared directory); `git clone`
  does not copy config.
- Fix: [#100](https://github.com/MCamner/atlas-core/pull/100). Git commands in
  observed or target repositories run with `-c core.fsmonitor=false`
  (`GIT_HARDENING` in `atlas_core/snapshot.py`, also used by
  `atlas_core/patch_proposal.py`).
- Merge SHA: `736529c315eebbeb66402d5055ac177df49d8214`; main CI
  [36296184118](https://github.com/MCamner/atlas-core/actions/runs/36296184118)
- Regression test: `tests/test_snapshot.py`
  `test_the_repositorys_own_config_cannot_run_a_command`
- Remaining: only `core.fsmonitor` is overridden. `atlas run --repo-path`
  runs only `rev-parse` and `status`. `atlas propose` runs more in the target
  repository, which is the caller's own: its `git diff` passes
  `--no-ext-diff` but not `--no-textconv`, so a textconv driver defined in
  that repository's config and selected by `.gitattributes` can run; and
  `update-ref` runs that repository's `reference-transaction` hook. Nothing
  enforces hardening for git subcommands added later.

### F2 — Approval screen could be altered by terminal control sequences

- Risk: `render()` wrote the diff and test output raw. Both come from the
  change being approved. Escape sequences in a patch erased an added line from
  the screen while the branch contained it.
- Fix: [#101](https://github.com/MCamner/atlas-core/pull/101). `_printable()`
  in `atlas_core/patch_proposal.py` spells out every Unicode Cc/Cf character
  except newline and tab. The written branch and `diff_sha256` are unchanged.
- Merge SHA: `9612145aa49fc0756b4fb8913eef8a57b6093e45`; main CI
  [36297143297](https://github.com/MCamner/atlas-core/actions/runs/36297143297)
- Regression test: `tests/test_patch_proposal.py`
  `test_control_characters_are_shown_not_interpreted`
- Remaining: visually confusable characters (homoglyphs, very long lines,
  a diff longer than the terminal scrollback) are not addressed.

### F3 — `Authorization` followed cross-origin redirects

- Risk: urllib's default redirect handler copied `Authorization` to any
  `Location`. The model API key and the GitHub token reached another host in
  a local test.
- Fix: [#102](https://github.com/MCamner/atlas-core/pull/102).
  `atlas_core/adapters/_http.py` drops `Authorization` when scheme, host or
  port changes; both adapters use it. Same-origin redirects keep it.
- Merge SHA: `f64dbd40e93286744863ebaab55cccedba79fe28`; main CI
  [36297326526](https://github.com/MCamner/atlas-core/actions/runs/36297326526)
- Regression test: `tests/test_redirect_credentials.py`
- Remaining: other headers are still forwarded as urllib does by default.
  An `https` → `https` redirect to the same host and port keeps the header by
  design. The https → http case is covered by the scheme check but not by a
  test with TLS.

### F5 — Provider reply read without a bound

- Risk: `UrllibTransport.post` read the whole response body before parsing.
- Fix: [#104](https://github.com/MCamner/atlas-core/pull/104). Reads at most
  `max_response_bytes` (16 MiB) and raises `ProviderBadResponse` beyond it.
- Merge SHA: `fe5ab12b9da9943a79f9f802d2c6e639c34d7a12`; main CI
  [36297597600](https://github.com/MCamner/atlas-core/actions/runs/36297597600)
- Regression test: `tests/test_provider_response_bound.py`
- Remaining: a slow endpoint is bounded by the per-socket-operation timeout,
  not by the run deadline, in the in-process API (documented limit R3).

### F6 — Redaction missed common current key formats

- Risk: `sk-proj-`/`sk-svcacct-`/`sk-admin-` OpenAI keys, Google `AIza…`
  keys, AWS secret access keys and opaque `Bearer` credentials were left in
  exported documents.
- Fix: [#105](https://github.com/MCamner/atlas-core/pull/105). Four patterns in
  `atlas_core/redaction.py`.
- Merge SHA: `31f9bd4bad323048c75fb0cbbf343384d6debd9d`; main CI
  [36297738377](https://github.com/MCamner/atlas-core/actions/runs/36297738377)
- Regression test: `tests/test_redaction.py` `TestCommonKeyShapes`
- Remaining: redaction matches known shapes only (documented limit R6). An
  AWS secret key without its variable name in front is not masked.

### O1 — GitHub reader accepted `.`/`..` as owner or name

- Risk: the name is placed in the request path. The host is fixed; no
  cross-host effect was found.
- Fix: [#106](https://github.com/MCamner/atlas-core/pull/106).
- Merge SHA: `6474f17d4ca6fa75d56f29d2475ad4bfcb1c7d60`; main CI
  [36297845486](https://github.com/MCamner/atlas-core/actions/runs/36297845486)
- Regression test: `tests/test_adapters.py`
  `test_dot_segments_are_not_a_repository`

Also fixed in the same period, not a security finding: `run-atlas.yml` ran
`pytest -q`, which stopped at collection
([#99](https://github.com/MCamner/atlas-core/pull/99), merge `7c2870c`, main
CI [36295967046](https://github.com/MCamner/atlas-core/actions/runs/36295967046)).

## Open finding

### F4 — Terminal approval does not prove a human approver

- Finding: the `atlas propose` approval code is the first 12 characters of the
  operation digest, printed on the same screen. The only check is that stdin
  is a terminal. A program running `atlas propose` under a pseudo-terminal it
  controls, such as an agent with shell access, read the code and approved its
  own write in a local test (`branch_created`).
- Status: open, design limit. [#103](https://github.com/MCamner/atlas-core/pull/103)
  (merge `a5ae194`, main CI
  [36297453084](https://github.com/MCamner/atlas-core/actions/runs/36297453084))
  changed only the documentation, so it no longer claims more than is
  enforced.
- Current guarantee: interactive, host-authorized approval. Whoever controls
  the terminal that runs `atlas propose` saw the operation digest, the exact
  diff and the test result, and typed the code. The approval is bound to that
  exact operation, single-use and time-limited (`atlas_core/approval.py`).
- Not claimed: that a human approved; any cryptographic or out-of-band proof
  of the approver.
- Guidance in the docs: a person who must approve runs `atlas propose`
  themselves; agents are given `--no-input`, which stops at
  `approval_required` with nothing written.
- Possible future control: an approval channel the agent cannot read or write,
  such as a separate host UI or local approval process, that issues the grant
  to `ApprovalAuthority`.
- For the reviewer: decide whether this limit blocks the v2.0 exit condition
  "no autonomous mutation without permission", or is acceptable as a
  documented residual risk.
