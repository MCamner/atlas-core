"""Atlas Core: standalone loop engine."""

from .controller import AtlasController
from .evidence_base import EvidenceBase
from .machine import STATE_MACHINE_VERSION, STOP_REASONS, StopClass
from .state import AtlasEvaluation, AtlasPlan, AtlasRoute, AtlasRunState
from .adapters.model import ModelAdapter, ModelResult, StubModelAdapter

__all__ = [
    "AtlasController",
    "EvidenceBase",
    "AtlasEvaluation",
    "AtlasPlan",
    "AtlasRoute",
    "AtlasRunState",
    "STATE_MACHINE_VERSION",
    "STOP_REASONS",
    "StopClass",
    "ModelAdapter",
    "StubModelAdapter",
    "ModelResult",
]
__version__ = "1.0.0"
