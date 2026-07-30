from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Protocol

class MemoryAdapter(Protocol):
    def read(self, query: str) -> list[str]: ...
    def write(self, record: dict) -> str | None: ...

class ToolAdapter(ABC):
    @abstractmethod
    def observe(self, task: str) -> list[str]:
        """Return observations relevant to a task."""
        raise NotImplementedError
