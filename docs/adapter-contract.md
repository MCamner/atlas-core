# Adapter Contract

Adapters may provide observations, memory reads/writes, repo reads, tool calls, or model calls.

Core must remain usable without any adapter.

This interface is part of the Atlas Core 1.x compatibility contract. Additive,
optional result metadata is allowed; changing method inputs or return types
requires a new major contract. See [api-contract.md](api-contract.md).

```python
class MemoryAdapter:
    def read(self, query: str) -> list[str]: ...
    def write(self, record: dict) -> str | None: ...
```

## Model adapter

Live model execution is optional and pluggable. Without a model adapter, Atlas Core uses the rule-based executor.

```python
class ModelAdapter:
    def execute(
        self,
        *,
        task: str,
        route: AtlasRoute,
        plan: AtlasPlan,
        observations: list[str],
        feedback: AtlasEvaluation | None = None,
    ) -> ModelResult: ...
```

`ModelResult` is provider-neutral:

```python
ModelResult(
    output="...",
    provider="fixture",
    model="fixture-model",
    metadata={"key": "value"},
)
```

Write-like tool use stays outside the model adapter contract. The controller still evaluates output and enforces the approval boundary before marking a run done.

## mqobsidian memory adapter

`MQObsidianMemoryAdapter` is optional and filesystem-based; importing Atlas Core does not require MQ packages. It reads only the compact surfaces defined by mqobsidian's context contract, in this order:

1. `.mq/context/task-pack.md`
2. `memory/learn/agent/<project>.md`
3. `systems/<project>/hot.md`
4. `systems/<project>/index.md`
5. `memory/context-cards/<project>-card.md`

The task pack is included only when its frontmatter `task` and `repo` exactly
match the current query and configured project.

Each observation is labelled as durable memory that must not be treated as current runtime truth. Duplicate content is returned once and symlinks outside the configured vault are ignored.

Writes validate the complete `atlas-memory-candidate.v1` shape, map it to
mqobsidian's canonical `memory-observation.v1`, and append it to
`memory/observations/atlas-core.observations.jsonl`. The stable observation id
deduplicates equivalent candidates while preserving producer, repository,
source-schema and content-hash provenance. Malformed existing JSONL fails
closed instead of being repaired or skipped.

## MQ read-only adapters

`MQMCPAdapter` projects an explicit list of host-supplied `MQToolContract`
objects into Atlas' `ToolGateway`. Only contracts whose authoritative
`safety_class` is exactly `read-only` are accepted; unknown, subprocess,
write-capable and dangerous tools fail during adapter construction. Input,
output, route, timeout and run-budget enforcement remain owned by the gateway.
An optional receiver gate runs before transport dispatch.

`MQAgentAdapter` uses the same explicit read-only contracts, but treats
mq-agent as an observation handoff. It returns JSON transport results as
labelled data and never transfers Atlas run state or evaluation ownership to
mq-agent. Both adapters depend only on the small `MQToolClient` protocol, so
Core imports and tests require no MQ package, endpoint or credentials.

Cross-repository compatibility is opt-in and kept outside the unit-test tree:

```bash
ATLAS_MQ_AGENT_REPO=/path/to/mq-agent \
ATLAS_MQ_MCP_REPO=/path/to/mq-mcp \
ATLAS_MQOBSIDIAN_REPO=/path/to/mqobsidian \
python -m pytest -q integrations/mq/test_mq_repository_contracts.py
```

The checks read only published contracts from those repositories. With no
paths configured they skip, so standalone Core CI requires none of the MQ
repositories or their runtime dependencies.

Future adapters: ChatGPTSkillAdapter, OpenAIModelAdapter.
