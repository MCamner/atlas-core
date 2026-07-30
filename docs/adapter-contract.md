# Adapter Contract

Adapters may provide observations, memory reads/writes, repo reads, tool calls, or model calls.

Core must remain usable without any adapter.

```python
class MemoryAdapter:
    def read(self, query: str) -> list[str]: ...
    def write(self, record: dict) -> str | None: ...
```

Future adapters: GitHubReaderAdapter, MQObsidianMemoryAdapter, ChatGPTSkillAdapter, OpenAIModelAdapter, FilesystemRepoAdapter.
