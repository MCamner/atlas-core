# Adapter Contract

Adapters may provide observations, memory reads/writes, repo reads, tool calls, or model calls.

Core must remain usable without any adapter.

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

Each observation is labelled as durable memory that must not be treated as current runtime truth. Writes accept only `atlas-memory-candidate.v1` records and place them under `inbox/atlas-memory-candidates/`.

Future adapters: ChatGPTSkillAdapter, OpenAIModelAdapter.
