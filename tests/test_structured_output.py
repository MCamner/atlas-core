"""P1.2 box two, reply side: a schema on the wire, and a local check either way.

Asking a provider for a shape and getting one are different events, and this
suite keeps them apart. The schema goes in the field each provider reads, and
the reply is read locally regardless — because an endpoint that merely
resembles one which supports `response_format` will accept the field and ignore
it, and a run that trusted the request would record an unchecked answer.

**The important behaviour is what a wrong shape becomes.** Not `tool_error`:
that ends the run and spends its stop reason on a machine failure, when what
happened is that a producer wrote the wrong thing. The reply passes through
untouched, the evaluator finds no usable findings block, and the run gets
`malformed_findings` with `repair_findings_block` — a gap the next pass closes
with what it already has.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any

from atlas_core import AtlasController, EvidenceBase
from atlas_core.adapters.live_model import (
    DEFAULT_OLLAMA_ENDPOINT,
    LiveModelAdapter,
    ProviderConfig,
)
from atlas_core.adapters.output_contract import (
    OUTPUT_SCHEMA_VERSION,
    _FINDING_ITEM,
    output_schema,
    read_envelope,
)
from atlas_core.evidence import FINDINGS_FENCE, structured_findings
from atlas_core.snapshot import collect_observation, take_snapshot

README = (
    "# Atlas Core\n"
    "\n"
    "pip install atlas-core\n"
    "\n"
    "En avgränsad loop-motor.\n"
)

REPORT = """# Repogranskning

Genomgången nedan bygger på de källor som lästes denna körning och täcker
dokumentation och installationsavsnitt i tillräcklig detalj för att motivera
slutsatserna. Texten är lång nog för att passera substanskravet, eftersom
poängen här är vad som händer med formen och inte med sakinnehållet.

## Observed sources
- `README.md`

## Verified findings
- {claim}

## Recommendation
Behåll installationsavsnittet.

## Next step
Inget.

## Confidence
Hög.
"""

SCHEMA_PATH = Path(__file__).parents[1] / "schemas" / "atlas-findings-block.v1.json"


class _Fake:
    """Returns one reply and keeps the payload it was sent."""

    def __init__(self, text: str, extra: dict[str, Any] | None = None):
        self.text = text
        self.extra = extra or {}
        self.payloads: list[dict[str, Any]] = []

    def post(
        self, url: str, payload: dict[str, Any], headers: dict[str, str], timeout: float
    ) -> dict[str, Any]:
        self.payloads.append(payload)
        return {"response": self.text, **self.extra}


class _FakeOpenAI(_Fake):
    def post(
        self, url: str, payload: dict[str, Any], headers: dict[str, str], timeout: float
    ) -> dict[str, Any]:
        self.payloads.append(payload)
        return {
            "choices": [{"message": {"content": self.text}}],
            **self.extra,
        }


class TestTheSchemaGoesOnTheWire(unittest.TestCase):
    """Per provider, in the field that provider reads. One schema, two fields —
    which is why this is per-spec and not one payload with a branch in it."""

    def _ollama(self, **kwargs: Any) -> tuple[LiveModelAdapter, _Fake]:
        transport = _Fake("hej")
        config = ProviderConfig(
            provider="ollama", model="llama3", endpoint=DEFAULT_OLLAMA_ENDPOINT
        )
        return LiveModelAdapter(config, transport=transport, **kwargs), transport

    def _openai(self, **kwargs: Any) -> tuple[LiveModelAdapter, _FakeOpenAI]:
        transport = _FakeOpenAI("hej")
        config = ProviderConfig(
            provider="openai_compatible",
            model="gpt-x",
            endpoint="https://example.invalid/v1/chat/completions",
            api_key="k",
        )
        return LiveModelAdapter(config, transport=transport, **kwargs), transport

    def _call(self, adapter: LiveModelAdapter) -> Any:
        controller = AtlasController(max_iterations=1, model_adapter=adapter)
        return controller.run("hej", json_mode=True)

    def test_ollama_receives_the_schema_in_format(self):
        """`/api/generate` takes a JSON Schema object in `format`, not only the
        string "json", so the schema is a request and not a suggestion."""
        adapter, transport = self._ollama()

        self._call(adapter)

        self.assertEqual(transport.payloads[0]["format"], output_schema())

    def test_an_openai_compatible_endpoint_receives_it_in_response_format(self):
        adapter, transport = self._openai()

        self._call(adapter)

        sent = transport.payloads[0]["response_format"]
        self.assertEqual(sent["type"], "json_schema")
        self.assertEqual(sent["json_schema"]["schema"], output_schema())
        self.assertTrue(sent["json_schema"]["strict"])

    def test_turning_it_off_sends_no_schema_field_at_all(self):
        """For an endpoint that rejects a request carrying a field it does not
        know. That is a configuration matter, not a fallback this module takes
        on its own — and the local check still runs, which the next test says."""
        adapter, transport = self._ollama(structured_output=False)

        self._call(adapter)

        self.assertNotIn("format", transport.payloads[0])

    def test_the_local_check_runs_even_with_no_schema_sent(self):
        """Asking is not the only way a reply can conform, and not asking is no
        reason to stop looking."""
        adapter, _ = self._ollama(structured_output=False)
        adapter.transport = _Fake(json.dumps({"report": "# Svar\n\nHej.", "findings": []}))

        run = self._call(adapter)
        metadata = run["metadata"]["model_result"]["metadata"]

        self.assertEqual(metadata["output_schema_sent"], "false")
        self.assertEqual(metadata["output_conformed"], "true")


class TestTheSchemaMatchesTheRepositorysContract(unittest.TestCase):
    """The schema is held in code because `schemas/` is documentation and is not
    packaged. That makes drift possible, so it is a test failure here rather
    than a wrong request in the field."""

    def setUp(self):
        self.filed = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))["items"]

    def test_the_same_fields_are_required(self):
        self.assertEqual(
            sorted(_FINDING_ITEM["required"]), sorted(self.filed["required"])
        )

    def test_the_same_properties_exist_and_no_others(self):
        self.assertEqual(
            sorted(_FINDING_ITEM["properties"]), sorted(self.filed["properties"])
        )
        self.assertFalse(_FINDING_ITEM["additionalProperties"])
        self.assertFalse(self.filed["additionalProperties"])

    def test_types_enums_and_patterns_agree(self):
        def constraints(node: Any) -> Any:
            """Everything that changes what validates, and nothing that does
            not. Descriptions differ by design: the filed ones are written for
            a person reading the repository, these for a producer."""
            if isinstance(node, dict):
                return {
                    key: constraints(value)
                    for key, value in sorted(node.items())
                    if key != "description"
                }
            if isinstance(node, list):
                return [constraints(item) for item in node]
            return node

        for name in self.filed["properties"]:
            with self.subTest(property=name):
                self.assertEqual(
                    constraints(_FINDING_ITEM["properties"][name]),
                    constraints(self.filed["properties"][name]),
                )

    def test_a_producer_still_cannot_declare_its_own_verdict(self):
        """The rule the filed schema exists to carry. A schema sent to a
        provider that re-opened this door would be worse than none."""
        for assigned in ("verdict", "verification_method", "finding_id"):
            self.assertNotIn(assigned, _FINDING_ITEM["properties"])
            self.assertNotIn(assigned, output_schema()["properties"])


class TestAConformingReplyBecomesWhatTheLoopReads(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        (self.root / "README.md").write_text(README, encoding="utf-8")
        self.snapshot = take_snapshot(self.root)
        self.observation = collect_observation(self.snapshot, "README.md", max_lines=5)
        self.base = EvidenceBase(snapshot=self.snapshot, observations=[self.observation])

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _finding(self) -> dict[str, Any]:
        claim = 'README.md lines 1-5 contain "pip install"'
        return {
            "claim": claim,
            "scope": "README.md",
            "severity": "P2",
            "severity_rationale": "Dokumentationsläge, inte en defekt.",
            "evidence": [
                {
                    "source_id": self.observation.source_id,
                    "content_sha256": self.observation.content_sha256,
                    "line_start": 3,
                    "line_end": 3,
                    "quoted": "pip install atlas-core",
                }
            ],
            "typed_claim": {
                "kind": "source_contains_literal",
                "source_id": self.observation.source_id,
                "text": "pip install",
            },
        }

    def _run(self, reply: str) -> Any:
        adapter = LiveModelAdapter(
            ProviderConfig(
                provider="ollama", model="llama3", endpoint=DEFAULT_OLLAMA_ENDPOINT
            ),
            transport=_Fake(reply),
        )
        controller = AtlasController(max_iterations=1, model_adapter=adapter)
        return controller.run("granska repo", evidence=self.base, json_mode=True)

    def test_the_envelope_is_rebuilt_into_prose_plus_the_fenced_block(self):
        finding = self._finding()
        envelope = read_envelope(
            json.dumps(
                {"report": REPORT.format(claim=finding["claim"]), "findings": [finding]}
            )
        )

        self.assertTrue(envelope.conformed)
        self.assertIsNone(envelope.reason)
        self.assertIn("## Verified findings", envelope.text)
        self.assertIn("```" + FINDINGS_FENCE, envelope.text)
        self.assertIsNone(structured_findings(envelope.text).malformed)

    def test_a_conforming_reply_is_graded_through_the_real_loop(self):
        """Not just parsed: the claim is settled against the lines the run read,
        which is the only thing the reassembly is for."""
        finding = self._finding()
        run = self._run(
            json.dumps(
                {"report": REPORT.format(claim=finding["claim"]), "findings": [finding]}
            )
        )
        record = run["evaluations"][-1]["citation_checks"][0]

        self.assertEqual(
            run["metadata"]["model_result"]["metadata"]["output_conformed"], "true"
        )
        self.assertTrue(record["citations_are_sound"])
        self.assertEqual(record["verdict"], "verified")

    def test_an_empty_findings_list_is_kept_and_not_dropped(self):
        """An explicit "nothing asserted" and a forgotten block are different
        states to whoever reads the run document."""
        envelope = read_envelope(json.dumps({"report": "# Svar\n\nInget.", "findings": []}))

        self.assertTrue(envelope.conformed)
        self.assertIn("```" + FINDINGS_FENCE + "\n[]\n```", envelope.text)


class TestAWrongShapeIsRepairableAndNotAFailedRun(unittest.TestCase):
    """The decision this half of the box turns on."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        (self.root / "README.md").write_text(README, encoding="utf-8")
        snapshot = take_snapshot(self.root)
        self.base = EvidenceBase(
            snapshot=snapshot,
            observations=[collect_observation(snapshot, "README.md", max_lines=5)],
        )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, reply: str) -> Any:
        adapter = LiveModelAdapter(
            ProviderConfig(
                provider="ollama", model="llama3", endpoint=DEFAULT_OLLAMA_ENDPOINT
            ),
            transport=_Fake(reply),
        )
        controller = AtlasController(max_iterations=1, model_adapter=adapter)
        return controller.run(
            "granska repo atlas-core", evidence=self.base, json_mode=True
        )

    def test_a_reply_of_the_wrong_shape_does_not_raise(self):
        adapter = LiveModelAdapter(
            ProviderConfig(
                provider="ollama", model="llama3", endpoint=DEFAULT_OLLAMA_ENDPOINT
            ),
            transport=_Fake("Jag hittade inget. Inget JSON här."),
        )
        from atlas_core.planner import build_plan
        from atlas_core.router import select_route

        route = select_route("granska repo")
        result = adapter.execute(
            task="granska repo",
            route=route,
            plan=build_plan("granska repo", route),
            observations=[],
        )

        self.assertEqual(result.output, "Jag hittade inget. Inget JSON här.")
        self.assertEqual(result.metadata["output_conformed"], "false")
        self.assertEqual(result.metadata["output_schema_gap"], "reply is not JSON")

    def test_the_run_stops_on_a_gap_and_not_on_tool_error(self):
        """`tool_error` would end the run and name a machine failure for what a
        producer wrote. The evaluator owns this case and can ask for a repair."""
        run = self._run("Ostrukturerad prosa utan JSON och utan block. " * 20)

        self.assertNotEqual(run["stop_reason"], "tool_error")
        self.assertIsNone(run["metadata"].get("failure"))

    def test_a_broken_findings_block_reaches_repair_findings_block(self):
        """Through the fence rather than the envelope: a provider that ignored
        the schema and wrote a block by hand is the case the evaluator already
        owned, and it still lands there."""
        broken = (
            REPORT.format(claim="README.md saknar installationsavsnitt")
            + "\n```"
            + FINDINGS_FENCE
            + "\n{ not json at all\n```\n"
        )
        run = self._run(broken)
        evaluation = run["evaluations"][-1]

        self.assertIn("malformed_findings", evaluation["evidence_gaps"])
        self.assertEqual(
            evaluation["next_action"]["kind"], "repair_findings_block"
        )

    def test_prose_with_no_block_reaches_repair_when_a_schema_was_asked_for(self):
        """The failure a provider is most likely to produce, and the one the
        earlier version of this suite did not establish.

        The output is well formed by every older measure: it records its
        sources under the heading the route wants and carries every required
        section. Read as text alone it is indistinguishable from a review that
        honestly asserts nothing — so the text cannot settle it, and the fact
        that a machine-readable block was *required* has to travel from the
        adapter that asked for one.
        """
        prose = REPORT.format(claim="README.md nämner pip install")
        run = self._run(prose)
        evaluation = run["evaluations"][-1]

        self.assertNotIn(FINDINGS_FENCE, prose)
        self.assertIn("## Observed sources", prose)
        self.assertIn("malformed_findings", evaluation["evidence_gaps"])
        self.assertEqual(evaluation["next_action"]["kind"], "repair_findings_block")
        self.assertFalse(evaluation["passed"])
        self.assertNotEqual(run["stop_reason"], "tool_error")

    def test_a_producer_that_was_asked_for_nothing_may_still_assert_nothing(self):
        """The compatibility limit of the rule above. Without a schema on the
        wire, prose with no block is the case this repository has always had:
        a review that records its sources and claims nothing. It is not a
        defect, and it must not become one."""
        adapter = LiveModelAdapter(
            ProviderConfig(
                provider="ollama", model="llama3", endpoint=DEFAULT_OLLAMA_ENDPOINT
            ),
            transport=_Fake(REPORT.format(claim="README.md nämner pip install")),
            structured_output=False,
        )
        run = AtlasController(max_iterations=1, model_adapter=adapter).run(
            "granska repo atlas-core", evidence=self.base, json_mode=True
        )
        evaluation = run["evaluations"][-1]

        self.assertNotIn("malformed_findings", evaluation["evidence_gaps"])

    def test_an_explicitly_empty_findings_list_is_not_a_missing_block(self):
        """A conforming envelope that asserts nothing keeps asserting nothing.
        The rule is about a block that is missing, not about one that is empty,
        and `[]` is the producer saying so."""
        run = self._run(json.dumps({"report": REPORT.format(claim="inget"), "findings": []}))
        evaluation = run["evaluations"][-1]

        self.assertNotIn("malformed_findings", evaluation["evidence_gaps"])

    def test_a_valid_handwritten_block_is_not_a_missing_block(self):
        """A provider that ignored the schema and answered correctly anyway.
        The rule must not punish it for the form it arrived in."""
        run = self._run(
            REPORT.format(claim="inget")
            + "\n```"
            + FINDINGS_FENCE
            + "\n[]\n```\n"
        )
        evaluation = run["evaluations"][-1]

        self.assertNotIn("malformed_findings", evaluation["evidence_gaps"])

    def test_nothing_observed_outranks_a_missing_block(self):
        """A run with no sources cannot be repaired by rewriting the answer, so
        the gap that says so must survive. Asking for a findings block when
        there is nothing to make findings about would be the wrong next step."""
        adapter = LiveModelAdapter(
            ProviderConfig(
                provider="ollama", model="llama3", endpoint=DEFAULT_OLLAMA_ENDPOINT
            ),
            transport=_Fake(REPORT.format(claim="inget")),
        )
        run = AtlasController(max_iterations=1, model_adapter=adapter).run(
            "granska repo atlas-core", json_mode=True
        )
        evaluation = run["evaluations"][-1]

        self.assertIn("no_sources_observed", evaluation["evidence_gaps"])
        self.assertNotIn("malformed_findings", evaluation["evidence_gaps"])

    def test_a_route_that_makes_no_findings_owes_no_block(self):
        """The rule is bounded by the route's own contract. A route that does
        not make findings is not failing by having none, and asking it for a
        block would be asking for something it was never for."""
        adapter = LiveModelAdapter(
            ProviderConfig(
                provider="ollama", model="llama3", endpoint=DEFAULT_OLLAMA_ENDPOINT
            ),
            transport=_Fake("Ett svar i ren prosa, utan block."),
        )
        run = AtlasController(max_iterations=1, model_adapter=adapter).run(
            "hej", json_mode=True
        )
        evaluation = run["evaluations"][-1]

        self.assertEqual(
            run["metadata"]["model_result"]["metadata"]["output_schema_sent"], "true"
        )
        self.assertNotIn("malformed_findings", evaluation["evidence_gaps"])

    def test_the_rule_holds_on_the_citation_only_path_too(self):
        """The older grading path, reached by a run with no `EvidenceBase`. It
        has its own "records its sources and asserts nothing" branch, which is
        the one that would otherwise read a missing block as an honest silence.
        """
        adapter = LiveModelAdapter(
            ProviderConfig(
                provider="ollama", model="llama3", endpoint=DEFAULT_OLLAMA_ENDPOINT
            ),
            transport=_Fake(
                "# Repogranskning\n\n"
                + "Genomgången är lång nog för substanskravet. " * 12
                + "\n\n## Observed sources\n- `README.md`\n\n"
                "## Recommendation\nInget.\n\n## Next step\nInget.\n\n"
                "## Confidence\nHög.\n"
            ),
        )
        run = AtlasController(max_iterations=1, model_adapter=adapter).run(
            "granska repo atlas-core",
            observations=["README.md:\n# Atlas Core"],
            json_mode=True,
        )
        evaluation = run["evaluations"][-1]

        self.assertIn("malformed_findings", evaluation["evidence_gaps"])
        self.assertEqual(evaluation["next_action"]["kind"], "repair_findings_block")

    def test_each_wrong_shape_says_which_one_it_was(self):
        """A reader of the run document is told what to fix, not that something
        was wrong."""
        cases = {
            "not json": ("hej", "reply is not JSON"),
            "a json list": ("[1, 2]", "reply is a JSON list, not an object"),
            "no report": ('{"findings": []}', "reply has no report text"),
            "empty report": ('{"report": "  ", "findings": []}', "reply has no report text"),
            "no findings": ('{"report": "x"}', "reply findings is missing"),
            "findings not a list": (
                '{"report": "x", "findings": {}}',
                "reply findings is not a list",
            ),
        }
        for name, (reply, reason) in cases.items():
            with self.subTest(case=name):
                envelope = read_envelope(reply)
                self.assertFalse(envelope.conformed)
                self.assertEqual(envelope.reason, reason)
                self.assertEqual(envelope.text, reply)

    def test_an_extra_top_level_field_is_not_conformity(self):
        """`additionalProperties: false` is in the schema that was sent, so a
        reply carrying a field it does not allow did not match it. `verdict` is
        the pointed example: a producer declaring its own success is the one
        thing this repository refuses everywhere else."""
        envelope = read_envelope(
            json.dumps({"report": "x", "findings": [], "verdict": "verified"})
        )

        self.assertFalse(envelope.conformed)
        self.assertIn("verdict", envelope.reason or "")

    def test_a_findings_entry_the_parser_cannot_use_is_not_conformity(self):
        """Judged by `structured_findings`, not by a second set of rules here.
        That module is the authority on what a finding must look like, and a
        validator beside it could only drift."""
        envelope = read_envelope(json.dumps({"report": "x", "findings": [42]}))

        self.assertFalse(envelope.conformed)
        self.assertIn("not usable", envelope.reason or "")

    def test_an_unusable_entry_is_still_rebuilt_so_the_evaluator_can_ask_for_a_repair(self):
        """Two different questions. The envelope held, so the reply is rebuilt
        and the findings reach the reader that reports `malformed_findings`.
        What did not hold is the claim that the whole reply matched the schema,
        and that is what `output_conformed` says."""
        envelope = read_envelope(json.dumps({"report": "x", "findings": [42]}))

        self.assertTrue(envelope.envelope_conformed)
        self.assertIn("```" + FINDINGS_FENCE, envelope.text)
        self.assertIsNotNone(structured_findings(envelope.text).malformed)

    def test_markdown_that_already_carries_a_block_passes_through_untouched(self):
        """A provider that ignored the schema and answered correctly anyway.
        This is the reply the adapter produced before a schema was ever sent,
        and it must keep working."""
        reply = "# Svar\n\n```" + FINDINGS_FENCE + "\n[]\n```\n"

        envelope = read_envelope(reply)

        self.assertFalse(envelope.conformed)
        self.assertEqual(envelope.text, reply)
        self.assertIsNone(structured_findings(envelope.text).malformed)


class TestWhatIsRecordedAboutTheConfiguration(unittest.TestCase):
    def _config(self, **overrides: Any) -> ProviderConfig:
        fields: dict[str, Any] = {
            "provider": "openai_compatible",
            "model": "gpt-x",
            "endpoint": "https://example.invalid/v1/chat/completions?token=SECRET",
            "api_key": "sk-not-a-real-key",
            "timeout": 30.0,
        }
        fields.update(overrides)
        return ProviderConfig(**fields)

    def test_the_id_is_stable_for_the_same_configuration(self):
        self.assertEqual(self._config().config_id, self._config().config_id)

    def test_it_changes_when_anything_that_changes_the_request_changes(self):
        base = self._config().config_id
        for field, value in (
            ("model", "gpt-y"),
            ("endpoint", "https://other.invalid/v1/chat/completions"),
            ("timeout", 31.0),
        ):
            with self.subTest(field=field):
                self.assertNotEqual(self._config(**{field: value}).config_id, base)

    def test_it_does_not_change_with_the_value_of_the_key(self):
        """Whether one is set changes what happens; which one it is does not.
        A digest over a secret is still derived from it."""
        self.assertEqual(
            self._config(api_key="sk-one").config_id,
            self._config(api_key="sk-two").config_id,
        )

    def test_neither_the_key_nor_the_endpoint_is_in_what_is_recorded(self):
        """The endpoint too: a URL can carry a token in its query string, which
        is why the digest is published and the address is not."""
        described = self._config().describe()

        self.assertNotIn("sk-not-a-real-key", json.dumps(described))
        self.assertNotIn("SECRET", json.dumps(described))
        self.assertNotIn("endpoint", described)
        self.assertEqual(described["config_id"], self._config().config_id)

    def test_the_configuration_and_schema_version_reach_the_run_document(self):
        transport = _Fake("hej")
        config = ProviderConfig(
            provider="ollama", model="llama3", endpoint=DEFAULT_OLLAMA_ENDPOINT
        )
        adapter = LiveModelAdapter(config, transport=transport)

        run = AtlasController(max_iterations=1, model_adapter=adapter).run(
            "hej", json_mode=True
        )
        metadata = run["metadata"]["model_result"]["metadata"]

        self.assertEqual(metadata["config_id"], config.config_id)
        self.assertEqual(metadata["provider"], "ollama")
        self.assertEqual(metadata["output_schema"], OUTPUT_SCHEMA_VERSION)

    def test_the_model_the_provider_says_it_served_is_recorded_beside_the_one_asked_for(self):
        """They can differ — an alias, a routed deployment — and a document that
        records only the request cannot tell you which one answered."""
        transport = _Fake("hej", {"model": "llama3:8b-instruct-q4"})
        adapter = LiveModelAdapter(
            ProviderConfig(
                provider="ollama", model="llama3", endpoint=DEFAULT_OLLAMA_ENDPOINT
            ),
            transport=transport,
        )

        run = AtlasController(max_iterations=1, model_adapter=adapter).run(
            "hej", json_mode=True
        )
        metadata = run["metadata"]["model_result"]["metadata"]

        self.assertEqual(metadata["model"], "llama3")
        self.assertEqual(metadata["provider_model"], "llama3:8b-instruct-q4")

    def test_a_provider_that_reports_no_version_reports_none(self):
        """Absent rather than an echo of what was asked for, which would read as
        confirmation."""
        adapter = LiveModelAdapter(
            ProviderConfig(
                provider="ollama", model="llama3", endpoint=DEFAULT_OLLAMA_ENDPOINT
            ),
            transport=_Fake("hej"),
        )

        run = AtlasController(max_iterations=1, model_adapter=adapter).run(
            "hej", json_mode=True
        )

        self.assertNotIn(
            "provider_model", run["metadata"]["model_result"]["metadata"]
        )


if __name__ == "__main__":
    unittest.main()
