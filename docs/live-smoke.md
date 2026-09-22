# Live smoke test

Everything else about the live model path runs in mandatory CI against a fake
transport. That exercises the real adapter, the real controller and the real
budget arithmetic without a daemon, a network route or a key, and it is the
right default: a suite that cannot run offline stops being a gate and becomes a
weather report.

What it cannot exercise is the one question that needed a provider to be real.
Atlas Core sends a JSON Schema in the field each provider reads — `format` for
Ollama, `response_format` for an OpenAI-compatible endpoint — and **asking for a
shape is not the same as getting one.** Until a real provider answered, the
claim "the reply is structured" rested on the request.

## Running it

It is off by default and needs two things, not one. A developer with
`ATLAS_MODEL_PROVIDER` set for ordinary use should not start making network
calls by running the test suite.

```bash
export ATLAS_MODEL_PROVIDER=ollama
export ATLAS_MODEL=qwen3:4b-instruct     # a model your Ollama actually has
export ATLAS_MODEL_TIMEOUT=170
export ATLAS_LIVE_SMOKE=1
python -m unittest discover -s tests -p 'test_live_smoke.py'
```

For a hosted endpoint, `ATLAS_MODEL_ENDPOINT` and `ATLAS_MODEL_API_KEY` must
also be set, and the provider name must be `openai_compatible`. That case is
**separately** opt-in and is not implied by the Ollama one passing: different
request field, different reply shape, different implementation of the same
schema.

## What it checks

An HTTP 200 is not a pass.

| Check | Why it is not trivial |
|---|---|
| The provider was reached | The daemon names the model it served, **read from the reply**, not echoed from the request. A cache or proxy returning a canned body would not carry it. |
| The schema was sent | `output_schema_sent`. Local knowledge, but it is what the rest is measured against. |
| The reply conformed | `output_conformed`. Its own test, so a model that answers but ignores the schema leaves exactly one assertion red. |
| Usage was metered | The run is budgeted, and `charge_tokens` raises `UnmeteredUsage` rather than charging zero when a provider reports no counts. A completed run has therefore already proved it. |
| The evaluator concluded | Otherwise this tests the adapter, not the loop. |
| No secret reached the document | Checked against the live configuration, where the values are real. |

## Measured

Read-only, against a local Ollama on 2026-09-22. One fixture repo with a
five-line `README.md`, the task *granska repot och svara på om README beskriver
installation*, one iteration, `max_prompt_chars=6000`, request timeout 120s.
**Nine runs, three each of three models**, produced by:

```bash
python3 scripts/live_smoke_measure.py docs/evidence/live-smoke-2026-09-22.jsonl
```

That script appends one JSON object per run as it completes, and the table
below is derived from that file — which is **kept**, at
[`docs/evidence/live-smoke-2026-09-22.jsonl`](evidence/live-smoke-2026-09-22.jsonl),
one line per run.

Keeping it is the point, not tidiness. These results are non-deterministic, so
running the script again produces a *different* measurement; it cannot
reproduce these nine observations. A table with no preserved rows behind it
would be a conclusion preserved without its evidence, which is the thing this
repository refuses from a producer. An earlier version of this table was
assembled by hand across three ad-hoc batches with different output truncation,
and its totals disagreed with its own rows.

The rows carry the model, the schema and conformity fields, token usage, wall
time, the stop reason and what the evaluator concluded. They carry no endpoint
and no key, for the same reason the run document does not.

| Model | Runs | Replies | Conformed | Tokens | Wall (s) |
|---|---|---|---|---|---|
| `qwen3:4b-instruct` | 3 | 3 | 3 of 3 | 905, 1123, 1083 | 27.2, 30.5, 29.5 |
| `llama3.2:latest` | 3 | 3 | 3 of 3 | 435, 119, 360 | 10.7, 0.6, 6.4 |
| `mq-learn:latest` | 3 | 3 | 3 of 3 | 1310, 1310, 1310 | 15.3, 12.3, 12.3 |

**The schema held on all nine.** `output_conformed` was `true` with no
`output_schema_gap`, on three models of which two are 3B. That is the claim
this document exists to settle, and for Ollama's `format` field it is settled —
for these models, at this time.

**All nine stopped `blocked`, and none of their findings survived.** Every run
produced a well-formed findings block and cited `README.md` with a
`content_sha256` it had invented, so every `citations_are_sound` was false and
every verdict was `insufficient_evidence`. The gaps were `unsound_citations`,
`plan_targets_unread` and `sources_not_documented`; the next action was always
`observe_again`, which is the host's and not the producer's. No run passed.

That is the loop behaving as designed, and it is worth stating plainly: **a
conforming reply is not a supported one.** The schema decides the *shape* of
what a producer says; the evidence layer decides whether any of it survives
contact with the bytes that were read. A model that fills in a plausible hash
gets nothing for it.

Every run also recorded `determinism: non_deterministic`, `tools_declared:
none` and `tools_invoked: 0`.

### A timeout, observed outside these nine

None of the nine runs above failed. A separate session did produce one, and it
is recorded here because a provider that sometimes does not answer is the
thing this whole page is about:

```
stop_reason: tool_error
failure: {"stage": "model_adapter",
          "error": "ProviderTimeout",
          "message": "ollama did not answer within 170s"}
```

`llama3.2:latest`, 170 seconds with no reply, minutes after an identical call
had returned in 18. The adapter raised the named exception from box two and the
controller stopped the run rather than falling back. It is not part of the
table because it is not part of that measurement.

## What this does not prove

- **Not that the next reply will conform.** A model is not a function. The same
  prompt to the same model may answer differently, which is why every such run
  carries `metadata.non_deterministic` and why that mark is written by the
  adapter rather than read out of the model's own text.
- **Not that the provider is reliable.** Nine runs without a failure is not a
  rate; a separate session timed out once on a model that had just answered in
  18 seconds.
- **Not anything about `openai_compatible`.** No such endpoint was configured
  here, so that half is untested rather than passing.
- **Not that what the model wrote is true.** Nothing here grades content. The
  nine runs above are the demonstration: conforming output, and not one settled
  claim.
- **Not a benchmark.** One fixture, one task, one iteration, three small local
  models, nine runs. It catches a regression in the live path. It characterises
  nothing.
