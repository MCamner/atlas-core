"""A run must tell its caller the truth about how it ended.

Two gaps, one theme. Both were recorded as open after the v1.0 review, and both
have to close before anything depends on a model adapter for grading:

- `model_adapter.execute()` had no error handling, so a provider failure left
  the loop as an unhandled exception rather than a terminal state.
- The CLI returned exit code 0 for every terminal state, so a caller could not
  tell "passed" from "gave up" without parsing prose — which
  docs/api-contract.md explicitly forbids.
"""

import io
import json
import unittest
from contextlib import redirect_stdout

from atlas_core import ModelResult, StubModelAdapter
from atlas_core.cli import EXIT_CODES, main
from atlas_core.controller import AtlasController

GOOD_OUTPUT = """# Fixture Answer

## Recommendation
Use the adapter output.

## Next step
Keep the controller loop around provider output.

## Confidence
High.
"""


class BoomAdapter:
    """A provider that fails the way real ones do: mid-call, with an exception."""

    def __init__(self, exc: Exception):
        self.exc = exc
        self.calls = 0

    def execute(self, **kwargs: object) -> ModelResult:
        self.calls += 1
        raise self.exc


class MalformedAdapter:
    """A provider that returns, but not what the contract promises."""

    def __init__(self, result: object):
        self.result = result

    def execute(self, **kwargs: object) -> ModelResult:
        return self.result  # type: ignore[return-value]


class TestModelAdapterFailureIsATerminalState(unittest.TestCase):
    def test_provider_error_becomes_a_controlled_stop(self):
        adapter = BoomAdapter(RuntimeError("upstream 503"))
        state = AtlasController(max_iterations=2, model_adapter=adapter).run(
            "hej", json_mode=True
        )

        self.assertEqual(state["status"], "failed")
        self.assertEqual(state["stop_reason"], "failed")
        self.assertEqual(adapter.calls, 1, "a failed provider must not be retried blindly")

    def test_the_failure_is_recorded_for_debugging(self):
        state = AtlasController(model_adapter=BoomAdapter(RuntimeError("upstream 503"))).run(
            "hej", json_mode=True
        )
        failure = state["metadata"]["failure"]

        self.assertEqual(failure["stage"], "model_adapter")
        self.assertEqual(failure["error"], "RuntimeError")
        self.assertIn("upstream 503", failure["message"])

    def test_a_long_provider_message_is_truncated(self):
        """Roadmap P2: log run parameters, never unbounded provider content."""
        state = AtlasController(model_adapter=BoomAdapter(RuntimeError("x" * 5000))).run(
            "hej", json_mode=True
        )

        self.assertLessEqual(len(state["metadata"]["failure"]["message"]), 512)

    def test_a_malformed_result_is_a_failure_not_a_false_success(self):
        for bad in (None, "just a string", ModelResult(output="")):
            with self.subTest(result=type(bad).__name__):
                state = AtlasController(model_adapter=MalformedAdapter(bad)).run(
                    "hej", json_mode=True
                )
                self.assertEqual(state["status"], "failed")
                self.assertEqual(state["stop_reason"], "failed")

    def test_a_failed_run_produces_no_evaluation_claiming_quality(self):
        state = AtlasController(model_adapter=BoomAdapter(RuntimeError("boom"))).run(
            "hej", json_mode=True
        )
        self.assertEqual(state["evaluations"], [])
        self.assertEqual(state["outputs"], [])

    def test_failure_is_never_a_passing_verdict(self):
        """`failed` is a runtime outcome. It must not look like a graded one.

        ROADMAP.md P0.3: "Skilj runtime-fel från saklig evaluering."
        """
        state = AtlasController(model_adapter=BoomAdapter(RuntimeError("boom"))).run(
            "hej", json_mode=True
        )

        self.assertEqual(state["stop_reason"], "failed")
        self.assertFalse(
            any(e["passed"] for e in state["evaluations"]),
            "a failed run must not carry a passing evaluation",
        )

    def test_failure_on_a_later_iteration_does_not_salvage_a_success(self):
        """The dangerous shape: pass 1 produced output, pass 2 died."""

        class FailsOnSecondCall:
            def __init__(self) -> None:
                self.n = 0

            def execute(self, **kwargs: object) -> ModelResult:
                self.n += 1
                if self.n == 1:
                    return ModelResult(output="# Svar\n\nKort.\n", provider="p", model="m")
                raise RuntimeError("provider died on pass 2")

        state = AtlasController(max_iterations=2, model_adapter=FailsOnSecondCall()).run(
            "hej", json_mode=True
        )

        self.assertEqual(state["status"], "failed")
        self.assertEqual(state["stop_reason"], "failed")
        self.assertEqual(len(state["outputs"]), 1, "pass 1's output is kept, not promoted")
        self.assertFalse(state["evaluations"][-1]["passed"])

    def test_a_keyboard_interrupt_is_not_swallowed_as_a_failed_run(self):
        """Ctrl-C is the operator stopping the run, not the provider failing."""
        adapter = BoomAdapter(KeyboardInterrupt())

        with self.assertRaises(KeyboardInterrupt):
            AtlasController(model_adapter=adapter).run("hej", json_mode=True)

    def test_the_run_still_serialises(self):
        state = AtlasController(model_adapter=BoomAdapter(RuntimeError("boom"))).run(
            "hej", json_mode=True
        )
        json.loads(json.dumps(state, ensure_ascii=False))


class TestStubAdapter(unittest.TestCase):
    """P2 DoD: the same test case runs deterministically with a mock adapter."""

    def test_stub_drives_the_model_path_without_a_provider(self):
        adapter = StubModelAdapter(GOOD_OUTPUT)
        state = AtlasController(model_adapter=adapter).run("hej", json_mode=True)

        self.assertEqual(state["outputs"], [GOOD_OUTPUT])
        self.assertEqual(state["metadata"]["model_result"]["provider"], "stub")
        self.assertEqual(len(adapter.calls), 1)

    def test_stub_records_what_it_was_asked(self):
        adapter = StubModelAdapter(GOOD_OUTPUT)
        AtlasController(model_adapter=adapter).run("hej", json_mode=True)

        self.assertEqual(adapter.calls[0]["route"].name, "general")


class TestCliExitCodes(unittest.TestCase):
    """docs/api-contract.md: callers use stop_reason, not prose."""

    def _run(self, argv):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = main(argv)
        return code, buffer.getvalue()

    def test_passed_run_exits_zero(self):
        code, _ = self._run(["run", "hej"])
        self.assertEqual(code, EXIT_CODES["passed"])
        self.assertEqual(code, 0)

    def test_incomplete_run_does_not_report_success(self):
        """A repo review with no sources gives up. It must not exit 0."""
        code, out = self._run(["run", "granska repo och hitta P0 P1 P2"])

        self.assertEqual(code, EXIT_CODES["no_actionable_retry"])
        self.assertNotEqual(code, 0)
        self.assertIn("no_actionable_retry", out)

    def test_approval_required_has_its_own_code(self):
        code, _ = self._run(["run", "skapa issue och pusha ändringen"])

        self.assertEqual(code, EXIT_CODES["approval_required"])
        self.assertNotIn(code, (0, EXIT_CODES["no_actionable_retry"]))

    def test_json_mode_uses_the_same_codes(self):
        code, out = self._run(["run", "granska repo och hitta P0 P1 P2", "--json"])

        self.assertEqual(code, EXIT_CODES["no_actionable_retry"])
        self.assertEqual(json.loads(out)["stop_reason"], "no_actionable_retry")

    def test_text_and_json_describe_the_same_run(self):
        """The text trailer is a rendering of the state, not a second source."""
        _, text = self._run(["run", "hej"])
        _, raw = self._run(["run", "hej", "--json"])
        state = json.loads(raw)

        self.assertIn(f"Stop reason: {state['stop_reason']}", text)
        self.assertIn(f"Atlas route: {state['route']['name']}", text)

    def test_every_declared_stop_reason_has_an_exit_code(self):
        from atlas_core.state import StopReason
        from typing import get_args

        for reason in get_args(StopReason):
            self.assertIn(reason, EXIT_CODES, f"{reason} has no documented exit code")

    def test_exit_codes_match_the_documented_table(self):
        """A published exit code is a contract. Drift here breaks callers."""
        import re
        from pathlib import Path

        doc = (Path(__file__).parents[1] / "docs" / "api-contract.md").read_text(
            encoding="utf-8"
        )
        table = doc.split("### CLI exit codes", 1)[1]
        documented = {
            reason: int(code)
            for code, reasons in re.findall(r"^\| (\d) \|[^|]*\|([^|]*)\|", table, re.M)
            for reason in re.findall(r"`(\w+)`", reasons)
        }

        self.assertEqual(documented, EXIT_CODES)


if __name__ == "__main__":
    unittest.main()
