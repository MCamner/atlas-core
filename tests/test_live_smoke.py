"""P1.2 box three: the one test that needs a provider to be real.

Everything else about the live path runs in mandatory CI against a fake
transport, which exercises the real adapter, the real controller and the real
budget arithmetic without a daemon, a network or a key. What it cannot
exercise is the only question that matters here: **does a provider actually
answer, and does it honour the schema it was sent?** Asking for `format` and
getting structured output back are different events, and no amount of local
testing distinguishes them.

So this file is opt-in. It is skipped unless `ATLAS_LIVE_SMOKE=1`, and skipped
again unless a provider is configured for it. Mandatory CI must never need a
daemon, a network route or a key, because a test suite that cannot run offline
stops being a gate and becomes a weather report.

**What a pass here means, exactly.** That this provider, at this endpoint, with
this model, answered conformingly at the moment the test ran. It is not a
promise about the next reply: a model is not a function, the model behind a
name can be replaced without the name changing, and nothing here says anything
about whether what the model *wrote* is true. That last question belongs to the
evidence layer, which decides it against observed lines and not against the
producer's confidence.

Run it, per `docs/live-smoke.md`:

    export ATLAS_MODEL_PROVIDER=ollama
    export ATLAS_MODEL=qwen3:4b-instruct
    export ATLAS_MODEL_TIMEOUT=60
    export ATLAS_LIVE_SMOKE=1
    python -m unittest discover -s tests -p 'test_live_smoke.py'
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any

from atlas_core import AtlasController, EvidenceBase
from atlas_core.adapters.live_model import (
    ENV_API_KEY,
    ENV_ENDPOINT,
    ENV_MODEL,
    ENV_PROVIDER,
    PromptLimits,
    model_adapter_or_raise,
)
from atlas_core.budget import RunLimits
from atlas_core.snapshot import collect_observation, take_snapshot

#: The switch. Not a default, and not inferred from a provider being
#: configured: a developer with `ATLAS_MODEL_PROVIDER` set for ordinary use
#: should not start making network calls by running the test suite.
ENV_SMOKE = "ATLAS_LIVE_SMOKE"

#: Small on purpose. A smoke test that needs a large prompt is testing the
#: provider's context window, which is not the question.
README = (
    "# Demo\n"
    "\n"
    "pip install demo\n"
    "\n"
    "Kör `demo --help` för att komma igång.\n"
)

TASK = "granska repot och svara på om README beskriver installation"


def _enabled() -> bool:
    return os.environ.get(ENV_SMOKE, "").strip() == "1"


def _provider() -> str:
    return (os.environ.get(ENV_PROVIDER) or "").strip()


def _configured_for(provider: str) -> bool:
    """Whether this provider is opt-in *and* has everything it needs.

    Per provider, deliberately. A passing Ollama run says nothing about a
    hosted endpoint: different request field, different reply shape, different
    implementation of the same schema. Reporting one as evidence for the other
    is the kind of claim this repository exists to refuse.
    """
    if not _enabled() or _provider() != provider:
        return False
    if not (os.environ.get(ENV_MODEL) or "").strip():
        return False
    if provider == "openai_compatible":
        return bool((os.environ.get(ENV_ENDPOINT) or "").strip()) and bool(
            (os.environ.get(ENV_API_KEY) or "").strip()
        )
    return True


class _LiveRun(unittest.TestCase):
    """One real call, shared by the assertions made about it.

    Made once per class rather than per test: a live call costs wall-clock and,
    on a hosted endpoint, money — and four assertions about one reply are more
    informative than four replies each asserted once, because the four are then
    about the same event.
    """

    provider = ""
    #: Not named `run`: `TestCase.run` is the method unittest calls to execute
    #: the case, and shadowing it with a dict makes every test in the class
    #: fail with "'dict' object is not callable".
    document: dict[str, Any] = {}
    tmp = ""

    @classmethod
    def setUpClass(cls) -> None:
        if not _configured_for(cls.provider):
            raise unittest.SkipTest(
                f"set {ENV_SMOKE}=1 and configure {cls.provider} to run this"
            )
        cls.tmp = tempfile.mkdtemp()
        root = Path(cls.tmp)
        (root / "README.md").write_text(README, encoding="utf-8")
        snapshot = take_snapshot(root)
        base = EvidenceBase(
            snapshot=snapshot,
            observations=[collect_observation(snapshot, "README.md", max_lines=10)],
        )
        adapter = model_adapter_or_raise(
            limits=PromptLimits(max_prompt_chars=6_000, max_observation_chars=1_500)
        )
        controller = AtlasController(max_iterations=1, model_adapter=adapter)
        cls.document = controller.run(
            TASK,
            evidence=base,
            json_mode=True,
            # Tight on purpose. A smoke test that can run for minutes or spend
            # an unbounded number of tokens is not a smoke test, and the budget
            # is part of what is being exercised: `charge_tokens` raises
            # `UnmeteredUsage` when a provider reports no counts, so a run that
            # completes here also proves the usage reached the budget.
            limits=RunLimits(
                wall_seconds=180.0,
                model_calls=2,
                tool_calls=0,
                tokens=200_000,
                output_bytes=200_000,
            ),
        )

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.tmp:
            shutil.rmtree(cls.tmp, ignore_errors=True)

    @property
    def model_metadata(self) -> dict[str, str]:
        return dict(self.document["metadata"]["model_result"]["metadata"])

    def test_the_provider_was_actually_reached(self):
        """Not an HTTP 200. The daemon names the model it served, which a
        canned reply from a proxy or a cache would not carry — and it is read
        from the reply rather than echoed from the request, so it cannot be a
        restatement of what was asked for."""
        self.assertIsNone(self.document["metadata"].get("failure"))
        self.assertNotEqual(self.document["stop_reason"], "tool_error")
        self.assertIn("provider_model", self.model_metadata)
        self.assertEqual(
            self.document["metadata"]["model_result"]["provider"], self.provider
        )

    def test_the_schema_was_sent_and_the_reply_is_reported_against_it(self):
        """That the request carried the schema is local knowledge; that the
        reply was measured against it is the part worth a live call."""
        metadata = self.model_metadata
        self.assertEqual(metadata["output_schema_sent"], "true")
        self.assertIn(metadata["output_conformed"], ("true", "false"))
        self.assertIn("output_schema", metadata)
        self.assertIn("config_id", metadata)

    def test_the_reply_conformed_to_the_schema_that_was_sent(self):
        """The claim that could not be established without a provider.

        Kept as its own test so a failure says *which* half broke. A model that
        answers but ignores the schema leaves this one red and the rest green,
        which is a useful result and not a broken suite — and it is reported
        per provider and model in `docs/live-smoke.md`, because it is a fact
        about that pair and not about Atlas Core.
        """
        metadata = self.model_metadata
        self.assertEqual(
            metadata["output_conformed"],
            "true",
            f"{self.provider}/{metadata.get('model')} did not conform: "
            f"{metadata.get('output_schema_gap')}",
        )

    def test_the_result_is_marked_as_not_reproducible(self):
        self.assertEqual(
            self.document["metadata"]["non_deterministic"],
            {"reason": "live_model_provider"},
        )
        self.assertEqual(self.model_metadata["determinism"], "non_deterministic")

    def test_the_usage_was_metered_and_the_evaluator_reached_a_conclusion(self):
        """A budgeted run that completed has already proved the first: the
        budget raises `UnmeteredUsage` rather than charging zero when a provider
        reports no counts. The second is what makes this a test of the loop and
        not of the adapter."""
        self.assertIn("usage_tokens", self.model_metadata)
        self.assertGreater(int(self.model_metadata["usage_tokens"]), 0)

        evaluation = self.document["evaluations"][-1]
        self.assertIn("passed", evaluation)
        self.assertIsInstance(evaluation["unmet_criteria"], list)

    def test_no_secret_reached_the_run_document(self):
        """Cheap to assert and the most expensive thing to get wrong. Checked
        against the live configuration rather than a fixture, because this is
        the one run where the values are real."""
        import json

        document = json.dumps(self.document)
        for name in (ENV_API_KEY, ENV_ENDPOINT):
            value = (os.environ.get(name) or "").strip()
            if value:
                with self.subTest(variable=name):
                    self.assertNotIn(value, document)


class TestOllama(_LiveRun):
    provider = "ollama"


class TestOpenAICompatible(_LiveRun):
    """Separately opt-in, and not implied by the Ollama one passing."""

    provider = "openai_compatible"


# The base class holds the assertions; running it on its own would run them
# with no provider named, which skips. Removed so the suite does not report a
# skip nobody asked for.
del _LiveRun


if __name__ == "__main__":
    unittest.main()
