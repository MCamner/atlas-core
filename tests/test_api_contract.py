import unittest

import atlas_core
from atlas_core.adapters.model import ModelResult
from atlas_core.controller import AtlasController


class OutputAdapter:
    def __init__(self, output: str):
        self.output = output

    def execute(self, **kwargs) -> ModelResult:
        return ModelResult(output=self.output, provider="test", model="fixture")


COMPLETE_OUTPUT = """## Recommendation
Use the bounded loop contract.

## Next step
Verify the public schemas.

## Confidence
High.
""" + ("evidence " * 40)


class TestStableApi(unittest.TestCase):
    def test_public_types_are_exported(self):
        for name in (
            "AtlasController",
            "AtlasEvaluation",
            "AtlasPlan",
            "AtlasRoute",
            "AtlasRunState",
            "ModelAdapter",
            "ModelResult",
            "STATE_MACHINE_VERSION",
            "STOP_REASONS",
            "StopClass",
        ):
            with self.subTest(name=name):
                self.assertIn(name, atlas_core.__all__)
                self.assertTrue(hasattr(atlas_core, name))

    def test_max_iterations_must_be_positive(self):
        for value in (0, -1, 1.5, True):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "max_iterations"):
                    AtlasController(max_iterations=value)  # type: ignore[arg-type]


class TestStopReasons(unittest.TestCase):
    def test_passed(self):
        state = AtlasController(model_adapter=OutputAdapter(COMPLETE_OUTPUT)).run(
            "hej", json_mode=True
        )
        self.assertEqual(state["status"], "done")
        self.assertEqual(state["stop_reason"], "passed")

    def test_approval_required(self):
        state = AtlasController(model_adapter=OutputAdapter(COMPLETE_OUTPUT)).run(
            "pusha ändringen", json_mode=True
        )
        self.assertEqual(state["status"], "need_user_approval")
        self.assertEqual(state["stop_reason"], "approval_required")

    def test_no_progress(self):
        short_complete = "## Recommendation\nx\n## Next step\ny\n## Confidence\nLow."
        state = AtlasController(model_adapter=OutputAdapter(short_complete)).run(
            "hej", json_mode=True
        )
        self.assertEqual(state["status"], "done")
        self.assertEqual(state["stop_reason"], "no_progress")

    def test_iteration_limit(self):
        state = AtlasController(
            max_iterations=1,
            model_adapter=OutputAdapter("incomplete " * 50),
        ).run("hej", json_mode=True)
        self.assertEqual(state["status"], "done")
        self.assertEqual(state["stop_reason"], "max_iterations")


if __name__ == "__main__":
    unittest.main()
