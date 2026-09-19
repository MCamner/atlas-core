"""Optional adapters for Atlas Core."""

from .model import ModelAdapter, ModelResult
from .mqobsidian import MQObsidianMemoryAdapter

__all__ = ["ModelAdapter", "ModelResult", "MQObsidianMemoryAdapter"]
