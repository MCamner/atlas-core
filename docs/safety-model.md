# Safety Model

Atlas Core's intended first use is read-only repository investigation. A
safety notice in a prompt is NOT an authorization check. The enforced code
paths and their limits are documented separately.

## Bounded read-only CLI (default)

The **public** `atlas run` CLI on POSIX launches a private Atlas worker in a
new process session. Its parent enforces `--wall-seconds` with a monotonic
clock, incrementally caps stdout/stderr, and kills the worker's **process
group**, including descendants that keep its pipes open, on timeout, output
overflow or interruption. A killed/crashed worker never supplies a partial
PASS: the parent emits a fresh, ungraded `budget_exhausted`, `cancelled` or
`tool_error` run document. The returned worker document must be valid JSON,
have the declared `atlas-run.v1` schema, and agree with its exit code and
terminal status. There is a separate 16 MiB maximum on the serialized worker
protocol, even if the operator requests a larger output budget. Windows
currently **fails closed** for this public bounded CLI because terminating a
whole Windows process tree requires a Job Object; no misleading hard-timeout
guarantee is made there.

Inside that worker, `atlas run` passes repository readers into the controller's
observing state **before** repository I/O. A single `RunBudget` counts local
file reads, GitHub GETs, observed UTF-8 text and controller output. Iteration
count is separately enforced by the controller. Defaults: `--wall-seconds 30`,
`--max-tool-calls 32`, `--max-output-bytes 65536`, `--max-iterations 2`.
There is no live model provider in this CLI; model-call and token quotas are
zero. Memory writes are disabled. Source or execution failures cannot turn
into a passing evaluation.

The local reader rejects candidates that escape the chosen root, limits reads
to the excerpt and checks the shared budget. The GitHub reader validates
`owner/name`, escapes the ref, charges each GET, limits response bytes and
uses the smaller of 15 seconds and the remaining deadline as request timeout.
Authentication, network and malformed-JSON errors fail closed; a missing
individual candidate file may be skipped.

`--memory-dir`, mqobsidian memory output and the old unbounded mode require the
explicit `--unsafe-legacy-unbounded` flag. These are NOT sandboxed or bounded.
Direct Python calls to `AtlasController.run(..., limits=None)` are also legacy.
**Embedded** `main([...])` deliberately stays an in-process API so hosts can
control their own isolation. It has cooperative budgeting but NOT the public
CLI's hard process deadline. Invoking the private `atlas_core.worker_cli`
module directly bypasses the parent, and is not a supported public entrypoint.

## Atlas-managed tool gateway (budgeted Python runs)

`AtlasController.run(..., limits=RunLimits(...))` shares one `RunBudget` across
iterations. When tools are registered, it supplies a `ToolGateway` to the
model adapter. Only trusted host code may register handlers. Unregistered
names and `write`/`network` capabilities are denied **before** a handler runs,
even when model text claims `approved: true`. Nested calls share the same
budget; retries never reset counters. Tool outputs must be JSON and are charged
to the UTF-8 output budget.

Each `ToolDefinition` also declares its route allowlist, input and output JSON
schemas, timeout, execution mode, idempotence and retry bound. The selected
route is set by the controller before model execution. Route and input failures
are denied before quota reservation or handler execution; output failures are
failed calls. Every retry reserves another tool call from the same run budget
and receives its own start/finish events. `max_attempts > 1` is rejected unless
the host explicitly sets `idempotent=True`.

`sandbox="isolated_process"` runs one call in a POSIX child session, caps IPC,
and kills the process group at the smaller of the tool timeout and remaining
run deadline. Nested tools are refused there because a forked budget would not
be shared accounting. `sandbox="in_process"` preserves nested calls and can
only detect timeout after a synchronous handler returns. Neither mode lowers
OS privileges; untrusted handlers still require a host-provided account or
container with read-only mounts and network policy.

Since P1.2 the live model adapter also declares **which** of those tools it may
ask for. `LiveModelAdapter.capabilities` is a list of tool names, **empty by
default**, set by host code holding the object and by nothing else — not from
the environment, because `ATLAS_MODEL_*` is read out of a process whose
variables a build script or a checked-in dotfile can set, which puts it closer
to repository content than to the host. It is a whitelist, so a tool nobody
thought about is denied rather than permitted until someone forbids it, and it
can only narrow: a declared `write` tool is still refused by the gateway.
`invoke_tool` is the single path and adds exactly that one check on top of the
gateway; there is no second registry and no branch that skips it.

Actual reported model tokens are mandatory. Locks prevent concurrent quota
oversubscription. Unmetered memory reads/writes are disabled in budgeted runs.

In-process adapters check the monotonic deadline and `cancelled` callback at
cooperative boundaries. Malformed explicitly-declared model JSON and provider
errors stop as `tool_error`, without a template fallback or a graded PASS.
Identical unproductive model outputs in bounded runs stop at `no_progress`.

## Hard-isolated Python API (explicit opt-in)

`from atlas_core import run_isolated` exposes
`run_isolated(controller, task, limits=RunLimits(...))` for hosts supplying
**trusted and spawn-picklable** model, reader and tool handlers. The process
uses Python `spawn`, starts a new POSIX session before callbacks execute, and
returns one versioned run document over capped JSON IPC. The parent applies a
hard monotonic deadline including startup, polls cancellation, kills the whole
worker process group on timeout/abort and rejects malformed or absent output
rather than promoting a partial answer. The child uses the same RunBudget for
all nested tool calls, retries and observations. Unpicklable callbacks fail
closed as `tool_error`. See `tests/test_p03_isolation.py` for non-cooperating
Python adapter, cancellation, nested quota and provider-failure regressions.

This boundary does **not** modify the compatible in-process `run()` API and
does **not** restrict the worker's OS privileges. A malicious installed adapter
can access filesystem/network APIs directly and may perform irreversible
side effects before the parent kills it. Only trusted adapters are in scope;
untrusted code needs a separately configured low-privilege sandbox with
read-only mounts/network policy. Windows currently fails closed for this API.

## Boundaries not provided by this implementation

- **The in-process Python API is not a hard timeout.** A synchronous model
  adapter or read handler can ignore `RunBudget.check()` indefinitely. Hosts
  using custom adapters MUST use `run_isolated` with trusted,
  spawn-picklable callbacks or provide an equivalent external process deadline
  and descendant termination contract. A provider should additionally
  enforce an I/O timeout. The public CLI's worker currently runs only the
  built-in deterministic executor and fixed repository readers.
- **A process is not a security sandbox.** It runs with the caller's OS user
  privileges, and arbitrary installed Python can bypass `ToolGateway` using
  filesystem/network APIs. For untrusted adapters, run as an unprivileged
  account/container with read-only mounts, restricted networking and explicit
  resource limits. Process termination does not undo side effects already
  committed before termination. Do not register unreviewed handlers as `read`.
- **No write-approval token exists.** Mutation tools remain denied. Future
  approval must bind to the exact diff, command, repository and ref, and be
  invalidated when that evidence changes. Approval-like model prose does
  not confer a capability.
- **Text is not evidence.** README/tool-output prompt injection cannot itself
  register a tool or grant permission, but Core does not guarantee that an
  arbitrary external model ignores malicious text.
- **The export is masked, and masking is narrow.** Since P0.1 the whole run
  document is redacted on the way out, including the prose `observations`
  channel that used to leave verbatim. The patterns cover credential shapes,
  home directories and email addresses — not arbitrary personal data — so
  inspect run logs before sharing them. `confidentiality` is derived from the
  same patterns and is never set to `public` automatically.

`requires_write_approval()` remains an advisory substring check, not the
execution gate. Atlas Core ships no live LLM or repository write adapter.

## Verification and P0.3 boundary

`tests/test_tool_gateway.py`, `tests/test_budget_concurrency.py`,
`tests/test_p03_controller.py`, `tests/test_p03_attack_matrix.py`,
`tests/test_p03_bounded_cli.py`, `tests/test_p03_progress.py` and
`tests/test_p03_hard_cli.py` and `tests/test_p03_isolation.py`
exercise denied mutations, malicious README/tool
output, nested and concurrent quotas, cancellation, provider/network failures,
malformed JSON, bounded source reads, identical-output stops and deliberately
non-cooperating worker processes. The standard repository workflow requests
read-only contents permissions.

The supported POSIX public CLI and explicit `run_isolated` API have
demonstrable parent-enforced deadlines. The in-process/legacy APIs remain
cooperative or unbounded. Neither process boundary is a filesystem/network
sandbox for arbitrary external Python; P0.3 completion is scoped accordingly.
