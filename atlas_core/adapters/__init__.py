"""Optional adapters for Atlas Core."""

from .live_model import (
    OUTPUT_SCHEMA_VERSION,
    LiveModelAdapter,
    NotConfigured,
    ProviderConfig,
    build_model_adapter,
    model_adapter_or_raise,
    output_schema,
    read_envelope,
)
from .model import ModelAdapter, ModelResult
from .mqobsidian import MQObsidianMemoryAdapter

__all__ = [
    "OUTPUT_SCHEMA_VERSION",
    "LiveModelAdapter",
    "ModelAdapter",
    "ModelResult",
    "MQObsidianMemoryAdapter",
    "NotConfigured",
    "ProviderConfig",
    "build_model_adapter",
    "model_adapter_or_raise",
    "output_schema",
    "read_envelope",
]
