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
installation*, one iteration, `max_prompt_chars=6000`, `ATLAS_MODEL_TIMEOUT=170`.
Seven runs across three models.

| Model | Runs | Conformed | Tokens | Stop reason |
|---|---|---|---|---|
| `qwen3:4b-instruct` | 1 | yes | 1053 | `blocked` |
| `llama3.2:latest` | 4 | 3 of 4 | 617, 863, 118 | `blocked`, once `tool_error` |
| `mq-learn:latest` | 1 | yes | 1310 | `blocked` |

**The schema held on every reply that arrived.** `output_conformed` was `true`
with no `output_schema_gap`, on all six replies across three models, two of
them 3B. That is the claim this document exists to settle, and for Ollama's
`format` field it is settled — for these models, at this time.

**One run did not arrive.** A `llama3.2:latest` call passed 170 seconds without
a reply, minutes after an identical one had returned in 18. The adapter raised
`ProviderTimeout`, the controller stopped `tool_error`, and
`metadata.failure` recorded `{"stage": "model_adapter", "error":
"ProviderTimeout", "message": "ollama did not answer within 170s"}` — the
failure naming from box two, doing its job on a failure nobody staged. Both the
passes and the timeout are real results about the same configuration.

**Every run that completed stopped `blocked`, with none of its findings
surviving.** Each model produced a well-formed findings block and cited
`README.md` with a `content_sha256` it had invented, so `citations_are_sound`
was false and every verdict stayed `insufficient_evidence`. The gaps were
`unsound_citations` and `plan_targets_unread`; the next action was
`observe_again`, which is the host's and not the producer's.

That is the loop behaving as designed, and it is worth stating plainly: **a
conforming reply is not a supported one.** The schema decides the *shape* of
what a producer says; the evidence layer decides whether any of it survives
contact with the bytes that were read. A model that fills in a plausible hash
gets nothing for it.

## What this does not prove

- **Not that the next reply will conform.** A model is not a function. The same
  prompt to the same model may answer differently, which is why every such run
  carries `metadata.non_deterministic` and why that mark is written by the
  adapter rather than read out of the model's own text.
- **Not that the provider is reliable.** One run in seven timed out, in the
  same session as passes on the same model.
- **Not anything about `openai_compatible`.** No such endpoint was configured
  here, so that half is untested rather than passing.
- **Not that what the model wrote is true.** Nothing here grades content. The
  three runs above are the demonstration: conforming output, and not one
  settled claim.
- **Not a benchmark.** One fixture, one task, one iteration, three small local
  models. It catches a regression in the live path. It characterises nothing.
