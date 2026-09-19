import json
import unittest
from pathlib import Path

from atlas_core.controller import AtlasController
from atlas_core.memory import build_memory_candidate

SCHEMA_DIR = Path(__file__).resolve().parents[1] / "schemas"

JSON_TYPES: dict[str, tuple[type, ...]] = {
    "object": (dict,),
    "array": (list,),
    "string": (str,),
    "boolean": (bool,),
    "integer": (int,),
    "number": (int, float),
    "null": (type(None),),
}


def load(name: str) -> dict:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


class SchemaAssertions(unittest.TestCase):
    """Minimal structural check: required keys, const values and declared types.

    Atlas Core ships no dependencies, so this is deliberately not a full
    JSON Schema implementation — it only proves the emitted documents and the
    schema files have not drifted apart.
    """

    def assert_matches(self, schema: dict, doc: dict, label: str) -> None:
        if schema.get("additionalProperties") is False:
            self.assertEqual(
                set(doc) - set(schema.get("properties", {})), set(),
                f"{label}: document contains undeclared properties",
            )
        for key in schema.get("required", []):
            self.assertIn(key, doc, f"{label}: missing required key {key!r}")
        for key, spec in schema.get("properties", {}).items():
            if key not in doc:
                continue
            if "const" in spec:
                self.assertEqual(doc[key], spec["const"], f"{label}.{key}")
            if "enum" in spec:
                self.assertIn(doc[key], spec["enum"], f"{label}.{key}")
            declared = spec.get("type")
            if not declared:
                continue
            names = declared if isinstance(declared, list) else [declared]
            expected = tuple(
                t
                for name in names
                for t in JSON_TYPES[name]
            )
            self.assertIsInstance(doc[key], expected, f"{label}.{key}")


class TestEmittedDocuments(SchemaAssertions):
    def test_run_matches_atlas_run_v1(self):
        state = AtlasController(max_iterations=2).run(
            "granska repo och hitta P0 P1 P2 förbättringar", json_mode=True
        )
        self.assert_matches(load("atlas-run.v1.json"), state, "run")

    def test_evaluations_match_atlas_evaluation_v1(self):
        state = AtlasController(max_iterations=2).run(
            "granska repo och hitta P0 P1 P2 förbättringar", json_mode=True
        )
        schema = load("atlas-evaluation.v1.json")
        self.assertTrue(state["evaluations"])
        for index, evaluation in enumerate(state["evaluations"]):
            self.assert_matches(schema, evaluation, f"evaluations[{index}]")

    def test_route_matches_atlas_route_v1(self):
        state = AtlasController().run("hej", json_mode=True)
        self.assert_matches(load("atlas-route.v1.json"), state["route"], "route")

    def test_memory_candidate_matches_schema(self):
        candidate = build_memory_candidate(
            task="granska repo", route_name="repo_review", output="x" * 100, quality_score=0.9
        )
        self.assert_matches(load("atlas-memory-candidate.v1.json"), candidate, "memory candidate")

    def test_run_is_json_serialisable(self):
        state = AtlasController(max_iterations=2).run("hej", json_mode=True)
        json.loads(json.dumps(state, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
