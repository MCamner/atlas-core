"""Opt-in contract checks against local MQ repository checkouts.

Standalone Atlas Core CI discovers this module but skips each check unless the
corresponding repository path is explicitly configured.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from types import ModuleType
import unittest

from atlas_core.adapters.mq import MQAgentAdapter, MQMCPAdapter, MQToolContract
from atlas_core.adapters.mqobsidian import MQObsidianMemoryAdapter


def _repo(variable: str) -> Path:
    raw = os.environ.get(variable)
    if not raw:
        raise unittest.SkipTest(f"set {variable} to run this MQ integration check")
    path = Path(raw).resolve()
    if not path.is_dir():
        raise AssertionError(f"{variable} is not a directory: {path}")
    return path


def _load_module(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location("atlas_mq_contract", path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load contract module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _NoCallClient:
    def call_tool(self, name: str, arguments: dict[str, object]) -> object:
        raise AssertionError(f"contract integration must not invoke {name}")


class TestMQRepositoryContracts(unittest.TestCase):
    def test_mq_mcp_safety_classes_fit_atlas_allowlist(self) -> None:
        root = _repo("ATLAS_MQ_MCP_REPO")
        document = json.loads(
            (root / "docs" / "tool_contracts.json").read_text(encoding="utf-8")
        )
        tools = document.get("tools")
        self.assertIsInstance(tools, list)
        by_class: dict[str, dict[str, object]] = {}
        for item in tools:
            if isinstance(item, dict) and isinstance(item.get("class"), str):
                by_class.setdefault(item["class"], item)
        self.assertTrue({"A", "B", "C", "D"}.issubset(by_class))

        accepted = [
            MQToolContract(str(by_class[kind]["name"]), safety_class="read-only")
            for kind in ("A", "B")
        ]
        self.assertEqual(
            set(MQMCPAdapter(_NoCallClient(), contracts=accepted).tools()),
            {contract.name for contract in accepted},
        )
        for kind, safety in (("C", "write-capable"), ("D", "subprocess")):
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                MQMCPAdapter(
                    _NoCallClient(),
                    contracts=[
                        MQToolContract(str(by_class[kind]["name"]), safety_class=safety)
                    ],
                )

    def test_mq_agent_normalization_matches_atlas_contract(self) -> None:
        root = _repo("ATLAS_MQ_AGENT_REPO")
        registry = _load_module(root / "mq_agent" / "tools" / "mcp_registry.py")
        normalize = registry.normalize_safety_class
        self.assertEqual(normalize("A"), "read-only")
        self.assertEqual(normalize("B"), "read-only")
        self.assertEqual(normalize("C"), "write-capable")
        self.assertEqual(normalize("D"), "subprocess")

        MQAgentAdapter(
            _NoCallClient(),
            contracts=[MQToolContract("read_repo_file", safety_class=normalize("A"))],
        )
        for kind in ("C", "D"):
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                MQAgentAdapter(
                    _NoCallClient(),
                    contracts=[MQToolContract("operation", safety_class=normalize(kind))],
                )

    def test_mqobsidian_mapping_matches_owned_schema(self) -> None:
        root = _repo("ATLAS_MQOBSIDIAN_REPO")
        try:
            import jsonschema
        except ImportError as exc:
            raise unittest.SkipTest("install jsonschema to validate mqobsidian") from exc

        schema = json.loads(
            (root / "schemas" / "memory-observation.v1.json").read_text(
                encoding="utf-8"
            )
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = MQObsidianMemoryAdapter(tmp, project="atlas-core").write(
                {
                    "schema": "atlas-memory-candidate.v1",
                    "created_at": "2026-09-25T12:00:00+00:00",
                    "task": "verify MQ adapter contracts",
                    "route": "repo_review",
                    "quality_score": 1.0,
                    "summary": "The MQ adapter contracts agree.",
                    "verified": True,
                    "public_safe": True,
                }
            )
            record = json.loads(Path(path).read_text(encoding="utf-8"))

        jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(
            record
        )


if __name__ == "__main__":
    unittest.main()
