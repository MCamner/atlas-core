"""Atlas Core: standalone loop engine."""

from .contracts import CONTRACTS, Contract, owner_of
from .controller import AtlasController
from .evidence_base import EvidenceBase
from .isolation import run_isolated
from .machine import STATE_MACHINE_VERSION, STOP_REASONS, StopClass
from .migrate import MigrationReport, UnknownSourceSchema, migrate_run
from .state import AtlasEvaluation, AtlasPlan, AtlasRoute, AtlasRunState
from .adapters.model import ModelAdapter, ModelResult, StubModelAdapter

__all__ = [
    "CONTRACTS",
    "Contract",
    "MigrationReport",
    "UnknownSourceSchema",
    "migrate_run",
    "owner_of",
    "AtlasController",
    "EvidenceBase",
    "run_isolated",
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
