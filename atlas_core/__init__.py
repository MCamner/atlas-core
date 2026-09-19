"""Atlas Core: standalone loop engine."""

from .controller import AtlasController
from .state import AtlasEvaluation, AtlasPlan, AtlasRoute, AtlasRunState
from .adapters.model import ModelAdapter, ModelResult, StubModelAdapter

__all__ = [
    "AtlasController",
    "AtlasEvaluation",
    "AtlasPlan",
    "AtlasRoute",
    "AtlasRunState",
    "ModelAdapter",
    "StubModelAdapter",
    "ModelResult",
]
__version__ = "1.0.0"
