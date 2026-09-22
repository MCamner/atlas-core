"""P1.2 box two, request side: a bounded prompt and a named failure.

Two things that only matter once a provider is real. An unbounded prompt is
the first thing that breaks against one, and a provider that fails does so in
several ways that call for different responses from whoever reads the run.

**Nothing is dropped quietly.** When the bound bites, the prompt says so in the
text the producer reads *and* the adapter counts it on the result. The two
readers are different: a model that knows it was shown part of a source can say
so, and a person reading the run document needs to know that "found nothing"
was said about less than the run holds. That is `Observation.read_in_full` one
layer up.

**Failures are named, not retried.** A retry inside the adapter would spend
wall-clock the `RunBudget` cannot see, and the loop already owns whether
another attempt is worth it. This layer owes a name, and it gives one through
the exception type — which the controller already writes into
`metadata.failure.error`, so no schema changed to carry it.
"""

from __future__ import annotations

import io
import json
import unittest
import urllib.error
from typing import Any

from atlas_core import AtlasController
from atlas_core.adapters.live_model import (
    DEFAULT_OLLAMA_ENDPOINT,
    BoundedPrompt,
    LiveModelAdapter,
    PromptLimits,
    ProviderBadResponse,
    ProviderConfig,
    ProviderRateLimited,
    ProviderRefused,
    ProviderTimeout,
    ProviderUnreachable,
    build_prompt,
)
from atlas_core.planner import build_plan
from atlas_core.router import select_route

TASK = "granska repo atlas-core"
ANSWER = "# Svar\n\n" + ("Innehåll som räcker. " * 40)


def _run_parts():
    route = select_route(TASK)
    return route, build_plan(TASK, route)


class TestThePromptStaysInsideItsBound(unittest.TestCase):
    def test_the_bound_holds_across_sizes(self):
        """The invariant, not one example of it.

        An earlier version reserved the truncation notice *after* slicing and
        the omission notice not at all, so it exceeded the bound it had just
        been handed — by a little at one size and more at another. A single
        example would have missed it.
        """
        route, plan = _run_parts()
        observations = ["x" * 9000, "y" * 9000, "z" * 9000]

        for limit in (600, 800, 2_000, 5_000, 12_000, 50_000):
            with self.subTest(limit=limit):
                prompt = build_prompt(
                    TASK, route, plan, observations, None,
                    PromptLimits(
                        max_prompt_chars=limit,
                        max_observation_chars=min(5_000, limit),
                    ),
                )
                self.assertLessEqual(len(prompt.text), limit)

    def test_a_prompt_that_fits_is_reported_complete(self):
        route, plan = _run_parts()

        prompt = build_prompt(TASK, route, plan, ["en kort källa"])

        self.assertTrue(prompt.is_complete())
        self.assertEqual(prompt.describe()["prompt_complete"], "true")
        self.assertIn("en kort källa", prompt.text)

    def test_a_truncated_source_says_so_in_the_text(self):
        route, plan = _run_parts()

        prompt = build_prompt(
            TASK, route, plan, ["x" * 9000], None,
            PromptLimits(max_prompt_chars=4_000, max_observation_chars=3_000),
        )

        self.assertEqual(prompt.truncated_observations, 1)
        self.assertIn("characters of this source are not", prompt.text)
        self.assertIn("about the part above", prompt.text)

    def test_an_omitted_source_says_so_in_the_text(self):
        """In the prompt, not only on the result. The producer is the one whose
        "I found nothing" would otherwise read as a statement about the repo."""
        route, plan = _run_parts()

        prompt = build_prompt(
            TASK, route, plan, ["x" * 9000, "y" * 9000, "z" * 9000], None,
            PromptLimits(max_prompt_chars=2_000, max_observation_chars=1_500),
        )

        self.assertGreater(prompt.omitted_observations, 0)
        self.assertIn("did not fit in this prompt", prompt.text)

    def test_sources_keep_the_order_the_run_holds_them(self):
        """So a producer that sees some sees the first ones, not an arbitrary
        subset. The host returned them in this order and the prompt keeps it."""
        route, plan = _run_parts()

        prompt = build_prompt(
            TASK, route, plan,
            ["FIRST" + "x" * 900, "SECOND" + "y" * 900, "THIRD" + "z" * 900],
            None,
            PromptLimits(max_prompt_chars=4_000, max_observation_chars=1_200),
        )

        self.assertLess(prompt.text.index("FIRST"), prompt.text.index("SECOND"))
        self.assertLess(prompt.text.index("SECOND"), prompt.text.index("THIRD"))

    def test_when_the_bound_bites_it_is_the_later_source_that_goes(self):
        """Room runs out at the end of the list, not the start."""
        route, plan = _run_parts()

        prompt = build_prompt(
            TASK, route, plan,
            ["FIRST" + "x" * 900, "SECOND" + "y" * 9000],
            None,
            PromptLimits(max_prompt_chars=1_300, max_observation_chars=1_000),
        )

        self.assertIn("FIRST", prompt.text)
        self.assertNotIn("SECOND", prompt.text)
        self.assertEqual(prompt.omitted_observations, 1)

    def test_a_source_too_big_to_keep_ends_the_prompt_rather_than_being_skipped(self):
        """The prefix promise, at the one place it used to break.

        A first source too large to truncate usefully was skipped, and a short
        second source was shown after it — so the producer saw source two and
        not source one, while the notice said only that one source "did not
        fit". That notice carries no identity: it means something only if what
        is shown is the first N in the run's order. So the first omission ends
        the selection, and everything after it is counted as omitted too.
        """
        route, plan = _run_parts()

        prompt = build_prompt(
            TASK, route, plan,
            ["FIRST" + "x" * 9000, "SECOND kort"],
            None,
            PromptLimits(max_prompt_chars=1_000, max_observation_chars=250),
        )

        self.assertNotIn("FIRST", prompt.text)
        self.assertNotIn("SECOND", prompt.text)
        self.assertEqual(prompt.omitted_observations, 2)

    def test_what_is_shown_is_always_a_prefix_of_what_the_run_holds(self):
        """The invariant behind the case above, over mixed sizes and bounds.

        Whatever the bound does, the sources that appear do so in run order and
        with nothing skipped in between: shown is the first N, for some N.
        """
        route, plan = _run_parts()
        sources = [
            "S0" + "a" * 50,
            "S1" + "b" * 9000,
            "S2" + "c" * 300,
            "S3" + "d" * 40,
            "S4" + "e" * 5000,
        ]
        marks = ["S0", "S1", "S2", "S3", "S4"]

        for budget in (900, 1_200, 2_000, 4_000, 9_000, 30_000):
            with self.subTest(budget=budget):
                limits = PromptLimits(
                    max_prompt_chars=budget,
                    max_observation_chars=min(400, budget),
                )
                prompt = build_prompt(TASK, route, plan, sources, None, limits)

                shown = [i for i, mark in enumerate(marks) if mark in prompt.text]
                self.assertEqual(shown, list(range(len(shown))))
                self.assertEqual(
                    prompt.omitted_observations, len(sources) - len(shown)
                )

    def test_the_instruction_is_never_cut(self):
        """A producer shown a truncated task is answering a different question,
        so an impossible bound is refused rather than quietly exceeded."""
        route, plan = _run_parts()

        with self.assertRaises(ValueError) as caught:
            build_prompt(
                TASK, route, plan, ["x" * 100], None,
                PromptLimits(max_prompt_chars=20, max_observation_chars=10),
            )

        self.assertIn("before any source is shown", str(caught.exception))

    def test_limits_that_contradict_each_other_are_refused(self):
        with self.assertRaises(ValueError):
            PromptLimits(max_prompt_chars=100, max_observation_chars=200)
        with self.assertRaises(ValueError):
            PromptLimits(max_prompt_chars=0)

    def test_what_was_shown_reaches_the_run_document(self):
        """The whole point of counting it."""
        class _Fake:
            def post(self, url: str, payload: dict[str, Any], headers: dict[str, str], timeout: float):
                return {"response": ANSWER}

        adapter = LiveModelAdapter(
            ProviderConfig(
                provider="ollama", model="llama3", endpoint=DEFAULT_OLLAMA_ENDPOINT
            ),
            transport=_Fake(),
            limits=PromptLimits(max_prompt_chars=1_500, max_observation_chars=900),
        )

        run = AtlasController(max_iterations=1, model_adapter=adapter).run(
            TASK, observations=["x" * 9000, "y" * 9000], json_mode=True
        )
        metadata = run["metadata"]["model_result"]["metadata"]

        self.assertEqual(metadata["prompt_complete"], "false")
        self.assertIn("observations_truncated", metadata)
        self.assertIn("observations_omitted", metadata)


class _Raises:
    def __init__(self, error: Exception):
        self.error = error
        self.calls = 0

    def post(self, url: str, payload: dict[str, Any], headers: dict[str, str], timeout: float):
        self.calls += 1
        raise self.error


def _http_error(code: int, retry_after: str | None = None) -> urllib.error.HTTPError:
    headers: Any = {} if retry_after is None else {"Retry-After": retry_after}
    return urllib.error.HTTPError(
        "https://example.invalid", code, "nope", headers, io.BytesIO(b"{}")
    )


class TestFailuresAreNamed(unittest.TestCase):
    def _adapter(self, error: Exception) -> tuple[LiveModelAdapter, _Raises]:
        transport = _Raises(error)
        return (
            LiveModelAdapter(
                ProviderConfig(
                    provider="ollama", model="llama3",
                    endpoint=DEFAULT_OLLAMA_ENDPOINT, timeout=5,
                ),
                transport=transport,
            ),
            transport,
        )

    def _call(self, adapter: LiveModelAdapter):
        route, plan = _run_parts()
        return adapter.execute(
            task=TASK, route=route, plan=plan, observations=[], feedback=None
        )

    def test_a_rate_limit_is_its_own_kind(self):
        adapter, _ = self._adapter(_http_error(429, "30"))

        with self.assertRaises(ProviderRateLimited) as caught:
            self._call(adapter)

        self.assertEqual(caught.exception.retry_after, 30.0)

    def test_a_rate_limit_without_a_hint_reports_none_not_a_default(self):
        """An invented number would be indistinguishable from one the provider
        actually sent."""
        adapter, _ = self._adapter(_http_error(429))

        with self.assertRaises(ProviderRateLimited) as caught:
            self._call(adapter)

        self.assertIsNone(caught.exception.retry_after)

    def test_an_http_date_hint_is_not_guessed_at(self):
        adapter, _ = self._adapter(_http_error(429, "Wed, 21 Oct 2026 07:28:00 GMT"))

        with self.assertRaises(ProviderRateLimited) as caught:
            self._call(adapter)

        self.assertIsNone(caught.exception.retry_after)

    def test_another_status_is_a_refusal(self):
        adapter, _ = self._adapter(_http_error(500))

        with self.assertRaises(ProviderRefused):
            self._call(adapter)

    def test_a_timeout_wrapped_in_urlerror_is_a_timeout(self):
        adapter, _ = self._adapter(urllib.error.URLError(TimeoutError()))

        with self.assertRaises(ProviderTimeout):
            self._call(adapter)

    def test_a_bare_timeout_is_a_timeout(self):
        adapter, _ = self._adapter(TimeoutError())

        with self.assertRaises(ProviderTimeout):
            self._call(adapter)

    def test_anything_else_unreachable_is_named_so(self):
        adapter, _ = self._adapter(urllib.error.URLError("connection refused"))

        with self.assertRaises(ProviderUnreachable):
            self._call(adapter)

    def test_a_body_that_is_not_json_is_a_bad_response(self):
        adapter, _ = self._adapter(json.JSONDecodeError("nope", "", 0))

        with self.assertRaises(ProviderBadResponse):
            self._call(adapter)

    def test_a_reply_of_the_wrong_shape_is_a_bad_response(self):
        class _Fake:
            def post(
                self,
                url: str,
                payload: dict[str, Any],
                headers: dict[str, str],
                timeout: float,
            ) -> Any:
                return ["not", "an", "object"]

        adapter = LiveModelAdapter(
            ProviderConfig(
                provider="ollama", model="llama3", endpoint=DEFAULT_OLLAMA_ENDPOINT
            ),
            transport=_Fake(),
        )

        with self.assertRaises(ProviderBadResponse):
            self._call(adapter)

    def test_no_failure_is_retried_inside_the_adapter(self):
        """A retry here would spend wall-clock the budget cannot see, and the
        loop already owns whether another attempt is worth it."""
        adapter, transport = self._adapter(_http_error(429, "1"))

        with self.assertRaises(ProviderRateLimited):
            self._call(adapter)

        self.assertEqual(transport.calls, 1)

    def test_the_kind_reaches_the_run_document(self):
        """Through the exception type the controller already records, so no
        schema changed to carry it."""
        adapter, _ = self._adapter(_http_error(429, "30"))

        run = AtlasController(max_iterations=2, model_adapter=adapter).run(
            TASK, json_mode=True
        )

        self.assertEqual(run["stop_reason"], "tool_error")
        self.assertEqual(run["metadata"]["failure"]["error"], "ProviderRateLimited")

    def test_the_message_carries_a_status_and_not_a_body(self):
        """A provider can echo a request header back in an error payload, and
        this message is written into the run document."""
        adapter, _ = self._adapter(_http_error(500))

        with self.assertRaises(ProviderRefused) as caught:
            self._call(adapter)

        self.assertIn("500", str(caught.exception))
        self.assertNotIn("nope", str(caught.exception))


class TestTheRecordShape(unittest.TestCase):
    def test_a_complete_prompt_describes_itself_as_one(self):
        prompt = BoundedPrompt(text="x")

        self.assertTrue(prompt.is_complete())
        self.assertEqual(prompt.describe()["observations_omitted"], "0")

    def test_either_kind_of_cut_makes_it_incomplete(self):
        self.assertFalse(BoundedPrompt(text="x", truncated_observations=1).is_complete())
        self.assertFalse(BoundedPrompt(text="x", omitted_observations=1).is_complete())


if __name__ == "__main__":
    unittest.main()
