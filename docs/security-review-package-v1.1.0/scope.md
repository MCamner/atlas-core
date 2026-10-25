# Scope

Pinned release SHA: `7d0d86c3ee88a8b2c62938d36d9fc77ae6fcfd58`

## In scope

Every change from `v1.0.0` (`8230fec`) to the pinned SHA that alters what Atlas
reads, runs, writes or sends, or what CI and the release build trust. That is
the set the next-release security gate in `ROADMAP.md` names:

- Runtime: #112, #114, #116, #119, #127, #128, #129, #134, #148, #151
- CI, dependencies and release build: #132, #133, #137, #138, #139, #140, #142,
  #143, #146, #147
- The E2E steps in `.github/workflows/test.yml` that check out and review the
  pinned mq-agent commit (#127, #128, #129)

The reviewer may also review the unchanged surfaces from the `v1.0.0` scope
(`../security-review-package/scope.md`). The `v1.0.0` review does not cover
how those surfaces interact with the new code. That interaction is in scope.

### Not named in the gate, but worth a look

| Commit | Why it is not named | What to check |
| --- | --- | --- |
| #141 `295224b` | Changes a docstring in `atlas_core/adapters/live_model.py` and documentation | Its `.secrets.baseline` change only moves `line_number` (see [`evidence.md`](evidence.md#secrets-baseline)) |
| #130 `8e1bfd3` | Changes the generated skill template in `atlas_core/skill_generator.py`, which `AGENTS.md` exempts | That the change is template text only |

## Out of scope

The same as for `v1.0.0`:

- Third-party or host-supplied adapters, tool handlers and model providers.
- How an external LLM behaves.
- Atlas One, atlas-loop and the MQ repositories, except where CI checks out
  mq-agent as review input.
- OS-level sandboxing.

## Trust boundaries

The boundaries from `v1.0.0` are unchanged in kind. These are the changes inside
them:

| Boundary | Change since `v1.0.0` |
| --- | --- |
| Repository content | Observations can start at an explicit line or at a bounded `anchor_prefix` (#119). Five exact gate-parity paths get a 200-line excerpt instead of 80 (#127). Deterministic producers now emit verified findings computed from observed text (#114, #116, #119, #127). |
| Model output | The output schema is unchanged from `v1.0.0`: #128 widened it and #148 restored it, so the model is offered only the two literal claim kinds. #151 adds an optional `ModelResult.findings_block`. `LiveModelAdapter` fills it from the reply's `findings`. Once the schema has been sent, that field is the only findings channel. An adapter that does not set it has its whole output read as findings (`adapter_output`), which is deprecated. |
| Findings block | New `atlas-findings-block.v2` and ```` ```atlas-findings.v2 ```` fence for `command_targets_differ`, emitted only by the gate-parity producer (#128, #148). Since #151, the evaluator reads findings only from what a producer wrote, never from the assembled output, which also carries observed repository text. |
| CI | Runs Atlas against the pinned mq-agent checkout. Audits the exported `uv.lock` rather than the environment (#146). Adds a Python 3.10 job (#143). Bumps pinned actions (#132, #138, #139). |
| Release build | The build backend `setuptools` is 84.2.1 (#140). The `tomli` fallback is used on Python 3.10 (#143). Version metadata is 1.1.0 (#147). |
| Environment, write approval, tool registration | No change since `v1.0.0`. `cli.py`, `approval.py`, `tool_gateway.py`, `patch_proposal.py` and `machine.py` are unchanged (see [`evidence.md`](evidence.md#unchanged-runtime-files)). |
| Run document | `atlas-run.v1` declares the optional `metadata.findings_sources`, which records per iteration where findings were read from (#151). |

## Entry points

The entry points are the same as in `v1.0.0`. The only one with new behaviour is
`atlas run` on the `repo_review` route. It has new topics: `ci` test-command
parity, `release_metadata`, `release_changelog` and `ci_gate_parity`. Each is
answered by a deterministic producer with no model call.
