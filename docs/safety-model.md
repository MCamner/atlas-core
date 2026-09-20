# Safety Model

Atlas Core's intended use is read-only repository investigation. A safety
notice in a prompt is NOT an authorization check. The enforced code paths and
remaining limits are documented separately.

## Bounded read-only CLI (default)

`atlas run` now passes repository readers into the controller's observing
state, **before** any repository I/O. A single `RunBudget` counts local file
reads, GitHub GET requests, observed UTF-8 output and the later controller
output; iteration count is separately enforced by the controller. CLI limits
are `--wall-seconds` (30), `--max-tool-calls` (32),
`--max-output-bytes` (65536) and `--max-iterations` (2). The CLI has no model
provider, so its model-call and token quotas are zero. It does not write
memory candidates in this mode. When a source read exceeds a quota, aborts,
or fails, the run stops at `budget_exhausted`, `cancelled` or `tool_error`
before being evaluated. The versioned state machine allows budget/control
stops during observation as well as during execution.

The local reader checks that candidate file paths remain inside the chosen
root, reads no more than the displayed excerpt in bounded mode, and checks
the shared deadline. The GitHub reader validates `owner/name`, percent-encodes
the ref, reserves one quota unit per GET, sets its request timeout to the
remaining deadline (capped at 15 seconds), limits response size and treats
network, HTTP authentication and malformed JSON failures as runtime errors.
A missing candidate file (HTTP 404) is skippable; unavailable repository
metadata or no readable standard files are not a passing investigation.

`--memory-dir` and mqobsidian memory options cannot be combined with bounded
CLI mode. They require the explicitly named `--unsafe-legacy-unbounded` flag,
which invokes the old API and does **not** claim resource or read-only limits.
Direct Python calls with `limits=None` are also legacy/unbounded; passing
`observations` as arbitrary prose is not equivalent to budgeted observation.

## Atlas-managed tool gateway (budgeted Python runs)

`AtlasController.run(..., limits=RunLimits(...))` shares one `RunBudget` across
iterations and passes a `ToolGateway` to the model adapter when tools are
registered. Host-registered `ToolDefinition` handlers are trusted code, not
model text. Unregistered tool names and `write`/`network` capabilities are
denied **before** any handler runs, irrespective of a text field claiming
`approved: true`. Nested calls use the same gateway; retries do not reset
counters. Tool outputs must be JSON and count against the UTF-8 output budget.
Actual token usage is required for budgeted model calls. Concurrent quota
reservations are protected by a lock. Budgeted memory reads and writes remain
disabled until a metered memory adapter exists.

The monotonic clock and optional `cancelled` callback are checked at each
cooperative boundary. A model declaring `metadata.format=json` but returning
malformed JSON fails as `tool_error`; provider errors do not fall back to a
template answer. A run stopped by budget/cancellation is not graded as PASS.

## Limits that P0.3 has NOT yet solved

- **No hard interruption of arbitrary synchronous Python callbacks.** A model
  adapter or trusted read handler can ignore its deadline while running.
  The next check stops the run, but an already-running call cannot be killed
  in-process. Untrusted code requires a separate process and enforced
  termination; provider adapters must use real I/O timeouts. The bounded CLI
  has timeouts for HTTP and cooperative checks for local reads, not a general
  OS-enforced deadline for every system call.
- **No OS sandbox.** The gateway controls Atlas-managed dispatch only.
  Arbitrary installed Python provided as a read handler or model adapter can
  use filesystem/network APIs directly, bypassing declared capabilities.
  The host must supply reviewed, least-privileged code or run it in an
  externally enforced sandbox. The tool registry is not writable by README
  contents or a model response.
- **No write-approval token.** Mutation tools are denied, not provisionally
  approved. Future authorization must bind a human's approval to the exact
  diff, command, repository and ref and invalidate when any of them changes.
- **Text is not fact verification.** README/tool-output prompt injection is
  tested against the registered gateway; Core cannot guarantee that an
  arbitrary external model ignores malicious text. The legacy `observations`
  export remains verbatim. Check run logs before sharing them.

`requires_write_approval()` remains a keyword-based advisory signal; it is
not the enforced gate. Repository text and tool output are data, never
capability grants. Atlas Core ships neither a live model provider nor a
repository write adapter.

## Verification

`tests/test_tool_gateway.py`, `tests/test_budget_concurrency.py`,
`tests/test_p03_controller.py`, `tests/test_p03_attack_matrix.py` and
`tests/test_p03_bounded_cli.py` cover malicious README/tool outputs,
write/network denial, nested quotas, concurrent budgets, cancellation,
network failure, malformed JSON, output bounds, stop reasons and source I/O
that fails before evaluation. The standard repository workflow requests
read-only content permissions for its task runner.

P0.3 is **not fully closed** until the arbitrary synchronous adapter/handler
boundary has an enforceable hard timeout or isolated-process contract, and
that boundary is verified with an intentionally non-cooperative fixture.
The legacy path must remain explicitly marked unsafe rather than being
silently counted as bounded.
