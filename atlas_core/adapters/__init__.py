"""Optional adapters for Atlas Core."""

from .live_model import (
    LiveModelAdapter,
    NotConfigured,
    ProviderConfig,
    build_model_adapter,
    model_adapter_or_raise,
)
from .model import ModelAdapter, ModelResult
from .mqobsidian import MQObsidianMemoryAdapter

__all__ = [
    "LiveModelAdapter",
    "ModelAdapter",
    "ModelResult",
    "MQObsidianMemoryAdapter",
    "NotConfigured",
    "ProviderConfig",
    "build_model_adapter",
    "model_adapter_or_raise",
]
