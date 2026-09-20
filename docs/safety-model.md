# Safety Model

Atlas Core's intended use is read-only repository investigation. A safety
notice in a prompt is NOT an authorization check. The mechanisms and their
actual limitations are documented separately below.

## Enforced for resource-limited runs

`AtlasController.run(..., limits=RunLimits(...))` shares one `RunBudget` across
iterations and, when tools are registered, passes a `ToolGateway` to the
model adapter. Registered handlers are trusted host code, not model text.
`ToolGateway.invoke()` is the only Atlas-managed tool dispatch path: an
unregistered name is denied; `write` and `network` capabilities are denied
before a handler executes, even if the request says `approved: true`.
Nested invocations use the *same* gateway and budget, and retries never reset
counters. Tool outputs must be strict JSON and count against the UTF-8 output
budget before reaching the caller. Actual reported tokens are required for
budgeted model calls; missing usage is a runtime error rather than zero.
Counters are guarded against concurrent oversubscription.

The monotonic clock is checked at the boundaries and on cooperative nested
calls. A caller can cancel through the `cancelled` callback; the run then
reports `cancelled`, never a graded PASS. A model reporting malformed JSON via
`metadata.format=json` fails as `tool_error`. A model/network exception also
fails as `tool_error`, with no template fallback.

A run with limits refuses an unmetered memory read or write. The normal
`--memory-dir` / mqobsidian settings are explicit external-memory opt-ins, not
approval for modifying a repository.

## Crucial limitations — do not claim these are enforced

- `limits=None` is still a backwards-compatible *unbounded legacy API path*.
  It cannot be presented as a bounded, production-safe run. Atlas-managed tool
  registration requires explicit limits, but the existing CLI reads repository
  context before calling the controller; those pre-run reads are not metered.
- A synchronous Python model adapter or tool handler cannot be forcibly
  stopped by a monotonic clock check. It MUST enforce a provider/network I/O
  timeout and check the shared budget in long-running and nested operations.
  If it ignores that contract, the host may exceed the deadline. The next
  check stops the run, but cannot undo effects already caused by a handler.
- The gateway is **not an OS sandbox**. Arbitrary Python provided as a model
  adapter or registered read handler can perform I/O outside this gateway.
  It is the host's responsibility to supply reviewed, least-privileged
  adapters and to isolate untrusted code at the process/container boundary.
  No runtime can prove that a handler declared `read` is pure Python.
- There is NO P0.3 write-approval protocol. Write handlers remain denied;
  text claiming human approval cannot grant rights. Future P2 approval must
  be bound to the exact command/diff/repository/ref and invalidated on change.
- Model output can contain instructions. The controller does not guarantee an
  arbitrary external model will ignore prompt injection. Repository text and
  tool results cannot *themselves* register a tool or grant a capability;
  all tool calls must cross the host-registered gateway. The legacy prose
  `observations` channel is still exported verbatim; do not share it without
  review. The `EvidenceBase` manifest has separate redaction rules.

## Existing read paths

`FilesystemRepoAdapter` reads fixed candidate paths under the caller's repo
path. `GitHubRepoAdapter` issues HTTP GETs to GitHub with a 15-second timeout
and an optional environment token; today it swallows certain network failures
and returns a prose observation, rather than a structured controller error.
`MQObsidianMemoryAdapter` reads five compact project surfaces and is disabled
in a budgeted controller run until it has a metered contract. The standalone
Core still ships no live LLM provider or repository write adapter.

`requires_write_approval()` is still a keyword-based *advisory* signal. It is
not the gateway's enforcement mechanism. Prompt text alone may neither
classify capabilities nor authorize a side effect.

## Negative tests and runner

`tests/test_tool_gateway.py`, `tests/test_budget_concurrency.py`,
`tests/test_p03_controller.py` and `tests/test_p03_attack_matrix.py` exercise
README and tool-output injection, denied write/network handlers, nested and
concurrent quotas, cancellation, network failures, malformed provider JSON,
retry bounds and cooperative timeouts. The workflow runner uses read-only
contents permissions for its normal task and passes dispatched task strings
through environment variables rather than shell interpolation.

P0.3 is **not fully closed** until the legacy/CLI observation paths are
bounded and arbitrary synchronous adapters have a demonstrated hard timeout
or an explicit process-isolation contract. Tests for cooperative checks do
not establish those stronger guarantees.
