import unittest
from typing import Any

from atlas_core.adapters import ModelResult
from atlas_core.controller import AtlasController


class FixtureModelAdapter:
    def __init__(self, output: str):
        self.output = output
        self.calls: list[dict[str, Any]] = []

    def execute(self, **kwargs: Any) -> ModelResult:
        self.calls.append(kwargs)
        return ModelResult(
            output=self.output,
            provider="fixture",
            model="fixture-model",
            metadata={"fixture": "true"},
        )


GOOD_OUTPUT = """# Fixture Answer

## Recommendation
Use the adapter output.

## Next step
Keep the controller loop around provider output.

## Confidence
High.
"""


class TestModelAdapterContract(unittest.TestCase):
    def test_controller_uses_model_adapter_output(self):
        adapter = FixtureModelAdapter(GOOD_OUTPUT)
        state = AtlasController(model_adapter=adapter).run("hej", json_mode=True)

        self.assertEqual(state["outputs"], [GOOD_OUTPUT])
        self.assertEqual(len(adapter.calls), 1)
        self.assertEqual(adapter.calls[0]["route"].name, "general")
        self.assertEqual(state["metadata"]["model_result"]["provider"], "fixture")
        self.assertEqual(state["metadata"]["model_result"]["model"], "fixture-model")

    def test_rule_based_executor_remains_default_fallback(self):
        state = AtlasController().run("hej", json_mode=True)

        self.assertIn("Atlas Core hanterar detta", state["outputs"][-1])
        self.assertNotIn("model_result", state["metadata"])

    def test_write_safety_still_gates_model_output(self):
        state = AtlasController(model_adapter=FixtureModelAdapter(GOOD_OUTPUT)).run(
            "skapa issue och pusha ändringen",
            json_mode=True,
        )

        evaluation = state["evaluations"][-1]
        self.assertTrue(evaluation["requires_user_approval"])
        self.assertEqual(state["status"], "need_user_approval")


if __name__ == "__main__":
    unittest.main()
