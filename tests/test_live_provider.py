"""P1.2 box one: a real provider, and the rule that a missing key is not one.

The roadmap states it in one line — *saknad nyckel får inte bryta deterministic
fallback* — and it collides with a rule this repository already had: a provider
that fails is `tool_error`, never a quiet fall back to the rule-based executor,
because answering deterministically and labelling it a model result reports an
answer nobody asked for.

Both hold because they are about different moments. A missing key is a
**configuration** state, answered by `build_model_adapter` returning `None` —
which is simply the absence the controller has always read as "run
deterministically". A failing request is a **request outcome**, and it stops
the run. The two never meet, and the tests below assert each of them.

No network. `_Fake` is the transport, so CI exercises the real adapter, the
real controller path and the real budget arithmetic without a daemon or a key.
"""

from __future__ import annotations

import json
import unittest
from typing import Any

from atlas_core import AtlasController
from atlas_core.adapters.live_model import (
    DEFAULT_OLLAMA_ENDPOINT,
    DEFAULT_TIMEOUT,
    ENV_API_KEY,
    ENV_ENDPOINT,
    ENV_MODEL,
    ENV_PROVIDER,
    ENV_TIMEOUT,
    LiveModelAdapter,
    NotConfigured,
    ProviderConfig,
    build_model_adapter,
    build_prompt,
    model_adapter_or_raise,
)
from atlas_core.budget import RunLimits
from atlas_core.planner import build_plan
from atlas_core.router import select_route

SECRET = "sk-do-not-leak-0123456789"
TASK = "granska repo atlas-core"

ANSWER = (
    "# Svar\n\nEn text som är lång nog att vara ett svar och inte en stump, "
    "med tillräckligt med innehåll för att passera substanskravet i den "
    "generella routen. " * 4
    + "\n\n## Recommendation\nX.\n\n## Next step\nY.\n\n## Confidence\nHög.\n"
)


class _Fake:
    """Records the call and returns a scripted reply, or raises."""

    def __init__(self, reply: dict[str, Any] | None = None, error: Exception | None = None):
        self.reply = reply if reply is not None else {"response": ANSWER}
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def post(
        self, url: str, payload: dict[str, Any], headers: dict[str, str], timeout: float
    ) -> dict[str, Any]:
        self.calls.append(
            {"url": url, "payload": payload, "headers": headers, "timeout": timeout}
        )
        if self.error is not None:
            raise self.error
        return self.reply


class TestAMissingKeyIsNotAFailure(unittest.TestCase):
    """The roadmap rule, in the one place it can hold."""

    def test_nothing_configured_is_no_adapter(self):
        self.assertIsNone(build_model_adapter({}))

    def test_a_hosted_provider_without_a_key_is_no_adapter(self):
        """Verbatim the case the rule names."""
        adapter = build_model_adapter(
            {
                ENV_PROVIDER: "openai_compatible",
                ENV_MODEL: "some-model",
                ENV_ENDPOINT: "https://example.invalid/v1/chat/completions",
            }
        )

        self.assertIsNone(adapter)

    def test_a_named_provider_without_a_model_is_no_adapter(self):
        self.assertIsNone(build_model_adapter({ENV_PROVIDER: "ollama"}))

    def test_the_run_still_completes_deterministically(self):
        """The point of returning None rather than raising.

        The controller has always read "no adapter" as "use the deterministic
        executor". Nothing new is needed for the fallback; it is the fallback.

        The stop reason is not asserted to be `passed`: `repo_review` without
        an evidence base cannot pass, and has not been able to since the
        citation-only path was closed. What the missing key must not do is turn
        a run into a provider failure or leave it with no answer at all.
        """
        run = AtlasController(
            max_iterations=1, model_adapter=build_model_adapter({})
        ).run(TASK, json_mode=True)

        self.assertIsNone(run["metadata"].get("model_result"))
        self.assertNotEqual(run["stop_reason"], "tool_error")
        self.assertNotIn("failure", run["metadata"])
        self.assertTrue(run["outputs"])

    def test_a_task_the_deterministic_path_can_finish_still_passes(self):
        """The other half, on a route that owes no evidence."""
        run = AtlasController(
            max_iterations=1, model_adapter=build_model_adapter({})
        ).run("förklara vad en avgränsad loop är", json_mode=True)

        self.assertEqual(run["stop_reason"], "passed")
        self.assertIsNone(run["metadata"].get("model_result"))

    def test_a_caller_that_wanted_a_live_run_hears_about_it(self):
        """Same absence, different question, so a different answer."""
        with self.assertRaises(NotConfigured):
            model_adapter_or_raise({})


class TestConfigurationStatedAndWrongIsAnError(unittest.TestCase):
    """Silence would leave a typo running the deterministic path unnoticed."""

    def test_an_unknown_provider_name_raises(self):
        with self.assertRaises(ValueError):
            build_model_adapter({ENV_PROVIDER: "not-a-provider", ENV_MODEL: "m"})

    def test_a_non_numeric_timeout_raises(self):
        with self.assertRaises(ValueError):
            build_model_adapter(
                {ENV_PROVIDER: "ollama", ENV_MODEL: "m", ENV_TIMEOUT: "soon"}
            )

    def test_a_timeout_of_zero_is_refused(self):
        """A call with no bound hangs the loop past the deadline it promised."""
        with self.assertRaises(ValueError):
            ProviderConfig(
                provider="ollama", model="m", endpoint="http://x", timeout=0
            )

    def test_a_keyed_provider_built_directly_without_a_key_is_refused(self):
        """The factory answers None; the type itself still will not be built
        into an unusable state."""
        with self.assertRaises(ValueError):
            ProviderConfig(
                provider="openai_compatible", model="m", endpoint="https://x"
            )


class TestTheRequest(unittest.TestCase):
    def _adapter(self, env: dict[str, str], fake: _Fake) -> LiveModelAdapter:
        adapter = build_model_adapter(env, transport=fake)
        assert adapter is not None
        return adapter

    def _call(self, adapter: LiveModelAdapter) -> Any:
        route = select_route(TASK)
        return adapter.execute(
            task=TASK,
            route=route,
            plan=build_plan(TASK, route),
            observations=[],
            feedback=None,
        )

    def test_ollama_posts_to_its_default_endpoint(self):
        fake = _Fake()
        adapter = self._adapter(
            {ENV_PROVIDER: "ollama", ENV_MODEL: "llama3"}, fake
        )

        result = self._call(adapter)

        self.assertEqual(fake.calls[0]["url"], DEFAULT_OLLAMA_ENDPOINT)
        self.assertEqual(fake.calls[0]["payload"]["model"], "llama3")
        self.assertIs(fake.calls[0]["payload"]["stream"], False)
        self.assertEqual(fake.calls[0]["timeout"], DEFAULT_TIMEOUT)
        self.assertEqual(result.provider, "ollama")
        self.assertEqual(result.output, ANSWER)

    def test_ollama_token_counts_reach_the_budget_field(self):
        """Without this a live run is unmetered while a scripted one is not."""
        fake = _Fake({"response": ANSWER, "prompt_eval_count": 12, "eval_count": 30})
        adapter = self._adapter({ENV_PROVIDER: "ollama", ENV_MODEL: "llama3"}, fake)

        result = self._call(adapter)

        self.assertEqual(result.metadata["usage_tokens"], "42")

    def test_a_reply_with_no_counts_reports_none_rather_than_zero(self):
        fake = _Fake({"response": ANSWER})
        adapter = self._adapter({ENV_PROVIDER: "ollama", ENV_MODEL: "llama3"}, fake)

        self.assertNotIn("usage_tokens", self._call(adapter).metadata)

    def test_a_hosted_provider_sends_its_key_as_a_header(self):
        fake = _Fake(
            {
                "choices": [{"message": {"content": ANSWER}}],
                "usage": {"total_tokens": 99},
            }
        )
        adapter = self._adapter(
            {
                ENV_PROVIDER: "openai_compatible",
                ENV_MODEL: "some-model",
                ENV_ENDPOINT: "https://example.invalid/v1/chat/completions",
                ENV_API_KEY: SECRET,
            },
            fake,
        )

        result = self._call(adapter)

        self.assertIn(SECRET, fake.calls[0]["headers"]["Authorization"])
        self.assertEqual(result.output, ANSWER)
        self.assertEqual(result.metadata["usage_tokens"], "99")

    def test_an_empty_reply_is_named_rather_than_returned(self):
        fake = _Fake({"response": "   "})
        adapter = self._adapter({ENV_PROVIDER: "ollama", ENV_MODEL: "llama3"}, fake)

        with self.assertRaises(RuntimeError) as caught:
            self._call(adapter)

        self.assertIn("ollama", str(caught.exception))


class TestTheKeyStaysWhereItWasPut(unittest.TestCase):
    def test_it_is_not_in_the_result(self):
        fake = _Fake({"choices": [{"message": {"content": ANSWER}}]})
        adapter = build_model_adapter(
            {
                ENV_PROVIDER: "openai_compatible",
                ENV_MODEL: "some-model",
                ENV_ENDPOINT: "https://example.invalid/v1/chat/completions",
                ENV_API_KEY: SECRET,
            },
            transport=fake,
        )
        assert adapter is not None
        route = select_route(TASK)

        result = adapter.execute(
            task=TASK, route=route, plan=build_plan(TASK, route),
            observations=[], feedback=None,
        )

        self.assertNotIn(SECRET, json.dumps(result.metadata))
        self.assertNotIn(SECRET, result.output)

    def test_it_is_not_in_the_run_document(self):
        fake = _Fake({"choices": [{"message": {"content": ANSWER}}]})
        adapter = build_model_adapter(
            {
                ENV_PROVIDER: "openai_compatible",
                ENV_MODEL: "some-model",
                ENV_ENDPOINT: "https://example.invalid/v1/chat/completions",
                ENV_API_KEY: SECRET,
            },
            transport=fake,
        )

        run = AtlasController(max_iterations=1, model_adapter=adapter).run(
            TASK, json_mode=True
        )

        self.assertNotIn(SECRET, json.dumps(run))
        self.assertEqual(run["metadata"]["model_result"]["provider"], "openai_compatible")

    def test_it_is_not_in_the_dataclass_repr(self):
        """The channel that survives being careful everywhere else.

        `describe()`, the metadata and the run document are all places this
        module chooses what to pass along. A dataclass `repr` is not: it is
        what a traceback prints, what a debugger shows, and what lands in a log
        line written by code that never thought about this field. `str()` falls
        back to it, so both are covered by the same `repr=False`.
        """
        config = ProviderConfig(
            provider="openai_compatible",
            model="some-model",
            endpoint="https://example.invalid/v1/chat/completions",
            api_key=SECRET,
        )

        self.assertNotIn(SECRET, repr(config))
        self.assertNotIn(SECRET, str(config))
        # Still there to be used, which is the point of hiding it rather than
        # dropping it.
        self.assertEqual(config.api_key, SECRET)
        self.assertIn("some-model", repr(config))

    def test_a_traceback_from_an_unrelated_failure_does_not_carry_it(self):
        """The concrete way the repr escapes: nothing here mentions the key."""
        config = ProviderConfig(
            provider="openai_compatible",
            model="some-model",
            endpoint="https://example.invalid/v1/chat/completions",
            api_key=SECRET,
        )

        with self.assertRaises(AssertionError) as caught:
            assert config.timeout < 0, f"unexpected config: {config!r}"

        self.assertNotIn(SECRET, str(caught.exception))

    def test_the_config_describes_itself_without_it(self):
        config = ProviderConfig(
            provider="openai_compatible",
            model="some-model",
            endpoint="https://example.invalid/v1/chat/completions",
            api_key=SECRET,
        )

        self.assertNotIn(SECRET, json.dumps(config.describe()))
        self.assertEqual(config.describe()["model"], "some-model")


class TestAFailingProviderStillStopsTheRun(unittest.TestCase):
    """The invariant this box must not weaken.

    Configuration absence is the fallback. A request that fails is not, and a
    run that asked for a model must not publish a deterministic answer as
    though a model had written it.
    """

    def test_a_transport_error_is_a_tool_error_not_a_fallback(self):
        fake = _Fake(error=OSError("connection refused"))
        adapter = LiveModelAdapter(
            ProviderConfig(
                provider="ollama", model="llama3", endpoint=DEFAULT_OLLAMA_ENDPOINT
            ),
            transport=fake,
        )

        run = AtlasController(max_iterations=2, model_adapter=adapter).run(
            TASK, json_mode=True, limits=RunLimits(
                wall_seconds=30, model_calls=4, tool_calls=0, tokens=100,
                output_bytes=100_000,
            ),
        )

        self.assertEqual(run["stop_reason"], "tool_error")
        self.assertEqual(run["metadata"]["failure"]["stage"], "model_adapter")
        self.assertEqual(run["outputs"], [])

    def test_it_does_not_retry_past_the_failure(self):
        fake = _Fake(error=OSError("connection refused"))
        adapter = LiveModelAdapter(
            ProviderConfig(
                provider="ollama", model="llama3", endpoint=DEFAULT_OLLAMA_ENDPOINT
            ),
            transport=fake,
        )

        AtlasController(max_iterations=3, model_adapter=adapter).run(
            TASK, json_mode=True
        )

        self.assertEqual(len(fake.calls), 1)


class TestThePrompt(unittest.TestCase):
    def test_it_carries_the_question_when_the_plan_has_one(self):
        from atlas_core.review_plan import build_review_plan

        route = select_route(TASK)
        plan = build_plan(TASK, route, snapshot_id="snap-1")
        prompt = build_prompt(TASK, route, plan, [])

        self.assertIn(TASK, prompt)
        self.assertIn(route.name, prompt)
        if plan.review is not None:
            self.assertIn(plan.review.question, prompt)
            self.assertEqual(
                plan.review.question,
                build_review_plan(TASK, "snap-1").question,
            )

    def test_feedback_goes_in_as_the_structured_action(self):
        """The channel the rest of this repository treats as the instruction.

        The prose beside it is for people; a producer is told the `kind` and
        the details, which is what a retry is supposed to act on.
        """
        route = select_route(TASK)
        plan = build_plan(TASK, route)
        run = AtlasController(max_iterations=1).run(
            "granska repo utan bevis", json_mode=True
        )
        del run

        from atlas_core.state import AtlasEvaluation, NextAction

        evaluation = AtlasEvaluation(
            quality_score=0.5,
            passed=False,
            met_criteria=[],
            unmet_criteria=["claims_are_settled"],
            reasons=["prosa"],
            missing=[],
            missing_sections=[],
            evidence_gaps=["uncited_findings"],
            next_action=NextAction(
                kind="cite_sources", gap_codes=["uncited_findings"],
                details={"fence": "atlas-findings"},
            ),
        )

        prompt = build_prompt(TASK, route, plan, [], evaluation)

        self.assertIn("cite_sources", prompt)
        self.assertIn("claims_are_settled", prompt)
        self.assertNotIn("prosa", prompt)


if __name__ == "__main__":
    unittest.main()
