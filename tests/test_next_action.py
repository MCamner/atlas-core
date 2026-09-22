"""P1.1 box four: feedback as data, and a retry that has to be worth it.

The evaluator already emitted gap *codes* — `evidence_gaps`, `missing_sections`,
`blocked_by` — and everything that said what to *do* about them was prose in
`suggested_adjustment`. A host or a model adapter reading that had to parse
English to find out whether it should re-cite, repair a block, or go and
observe a source again, which is the thing `docs/api-contract.md` tells
adapters not to do.

`next_action` is that instruction as data: one `kind` from a closed
vocabulary, the gap codes it addresses, who has to act, and the specifics the
actor needs. The prose stays beside it for humans.

The second half is the retry gate. In a bounded run the loop already refused to
spend an iteration on a producer that returned byte-identical output. Identical
bytes are a narrow test: a producer can reword its answer, fail in exactly the
same way, and buy another iteration with nothing. What matters is whether the
*failure* moved.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any

from atlas_core import AtlasController
from atlas_core.adapters.model import ModelResult
from atlas_core.budget import RunLimits
from atlas_core.evidence import FINDINGS_FENCE
from atlas_core.evidence_base import EvidenceBase
from atlas_core.snapshot import collect_observation, take_snapshot

README = "# Atlas Core\n\npip install atlas-core\n\nEn avgränsad loop-motor.\n"

REPO_TASK = "granska repo atlas-core"

PROSE = """# Repogranskning

Granskningen nedan bygger på de källor som lästes denna körning och går igenom
repots dokumentation, testupplägg och släppprocess i tillräcklig detalj för att
motivera de slutsatser som dras. Texten är avsiktligt lång nog för att passera
substanskravet, eftersom poängen är vad loopen gör med ett fynd som inte håller.

## Observed sources
- `README.md`

## Findings
- {claim}

## Recommendation
Lägg till ett installationsavsnitt.

## Next step
Skriv avsnittet.

## Confidence
Hög.
"""


class _ScriptedAdapter:
    """Returns each output in turn, so two passes can differ on purpose."""

    def __init__(self, *outputs: str):
        self.outputs = list(outputs)
        self.calls = 0

    def execute(self, **kwargs: Any) -> ModelResult:
        output = self.outputs[min(self.calls, len(self.outputs) - 1)]
        self.calls += 1
        return ModelResult(
            output=output,
            provider="test",
            model="scripted",
            metadata={"usage_tokens": "1"},
        )


class _Repo(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (self.root / "README.md").write_text(README, encoding="utf-8")
        self.snapshot = take_snapshot(self.root)
        self.observation = collect_observation(self.snapshot, "README.md")
        self.base = EvidenceBase(
            snapshot=self.snapshot, observations=[self.observation]
        )

    def _citation(self, **overrides: Any) -> dict[str, Any]:
        fields: dict[str, Any] = {
            "source_id": self.observation.source_id,
            "content_sha256": self.observation.content_sha256,
            "line_start": 1,
            "line_end": 1,
            "quoted": "# Atlas Core",
        }
        fields.update(overrides)
        return fields

    def _output(
        self,
        claim: str = "README.md saknar installationsinstruktioner.",
        *,
        citations: list[dict[str, Any]] | None = None,
        block: bool = True,
        typed: dict[str, Any] | None = None,
        sections: bool = True,
        raw_block: str | None = None,
    ) -> str:
        text = PROSE.format(claim=claim)
        if not sections:
            text = text.split("## Recommendation")[0]
        if raw_block is not None:
            return text + "\n```" + FINDINGS_FENCE + "\n" + raw_block + "\n```\n"
        if not block:
            return text
        finding: dict[str, Any] = {
            "claim": claim,
            "scope": "README.md",
            "severity": "P1",
            "severity_rationale": "Blockerar en ny användare.",
            "evidence": citations if citations is not None else [self._citation()],
        }
        if typed is not None:
            finding["typed_claim"] = typed
        return (
            text + "\n```" + FINDINGS_FENCE + "\n" + json.dumps([finding]) + "\n```\n"
        )

    def _run(self, output: str, **kwargs: Any) -> dict[str, Any]:
        controller = AtlasController(
            max_iterations=kwargs.pop("max_iterations", 1),
            model_adapter=_ScriptedAdapter(output),
        )
        return controller.run(
            REPO_TASK, evidence=self.base, json_mode=True, **kwargs
        )

    def _action(self, run: dict[str, Any]) -> dict[str, Any]:
        action = run["evaluations"][-1]["next_action"]
        self.assertIsNotNone(action, "expected a next action on a failing run")
        return action


class TestTheActionIsNamedAsData(_Repo):
    def test_a_finding_with_no_citation_block_asks_for_citations(self):
        run = self._run(self._output(block=False))
        action = self._action(run)

        self.assertEqual(action["kind"], "cite_sources")
        self.assertEqual(action["actor"], "producer")
        self.assertIn(
            self.observation.source_id, action["details"]["available_source_ids"]
        )

    def test_an_unreadable_block_asks_for_it_to_be_repaired_first(self):
        """Structure before content: no citation could be read at all."""
        run = self._run(self._output(raw_block="{not json"))
        action = self._action(run)

        self.assertEqual(action["kind"], "repair_findings_block")
        self.assertIn("malformed_findings", action["gap_codes"])

    def test_a_broken_citation_asks_for_a_re_cite_and_names_the_status(self):
        run = self._run(
            self._output(citations=[self._citation(quoted="text som inte finns där")])
        )
        action = self._action(run)

        self.assertEqual(action["kind"], "recite_from_source")
        statuses = action["details"]["citations"][0]["statuses"]
        self.assertIn("quote_mismatch", statuses)

    def test_a_refuted_claim_is_named_for_dropping(self):
        typed = {
            "kind": "source_lacks_literal",
            "source_id": self.observation.source_id,
            "text": "pip install",
        }
        from atlas_core.claim_check import ClaimKind, TypedClaim

        rendered = TypedClaim(
            kind=ClaimKind.LACKS,
            source_id=self.observation.source_id,
            text="pip install",
        ).render(self.observation.path, 1, self.observation.line_end)
        run = self._run(self._output(rendered, typed=typed))
        action = self._action(run)

        self.assertEqual(action["kind"], "drop_refuted_claim")
        self.assertTrue(action["details"]["claims"])

    def test_a_moved_source_asks_the_host_to_observe_again(self):
        """The producer cannot fix this one, and the record says so."""
        run_output = self._output()
        (self.root / "README.md").write_text(README + "ändrad\n", encoding="utf-8")
        run = self._run(run_output)
        action = self._action(run)

        self.assertEqual(action["kind"], "observe_again")
        self.assertEqual(action["actor"], "host")
        self.assertIn("stale_source", action["details"]["blocked_by"])

    def test_observing_again_outranks_every_repairable_gap(self):
        """A citation cannot be repaired against a source that has moved."""
        run_output = self._output(
            citations=[self._citation(quoted="text som inte finns där")], sections=False
        )
        (self.root / "README.md").write_text(README + "ändrad\n", encoding="utf-8")
        run = self._run(run_output)
        action = self._action(run)

        self.assertEqual(action["kind"], "observe_again")
        self.assertIn("recommendation", action["gap_codes"])

    def test_a_formatting_gap_alone_asks_for_the_sections(self):
        """A route with no evidence contract still gets a named action.

        Short enough to miss the substance threshold as well, so the run does
        not pass — a passing run is told nothing, which the test below covers.
        """
        run = AtlasController(
            max_iterations=1, model_adapter=_ScriptedAdapter("# Svar\n\nKort.\n")
        ).run("hej", json_mode=True)
        action = run["evaluations"][-1]["next_action"]

        self.assertEqual(action["kind"], "add_sections")
        self.assertEqual(
            sorted(action["details"]["sections"]),
            ["confidence", "next_step", "recommendation"],
        )
        self.assertEqual(action["actor"], "producer")

    def test_a_passing_run_has_nothing_to_do_next(self):
        from atlas_core.claim_check import ClaimKind, TypedClaim

        typed = TypedClaim(
            kind=ClaimKind.CONTAINS,
            source_id=self.observation.source_id,
            text="pip install",
        )
        claim = typed.render(self.observation.path, 1, self.observation.line_end)
        run = self._run(
            self._output(
                claim,
                typed={
                    "kind": typed.kind.value,
                    "source_id": typed.source_id,
                    "text": typed.text,
                },
            )
        )

        self.assertEqual(run["stop_reason"], "passed")
        self.assertIsNone(run["evaluations"][-1]["next_action"])

    def test_a_run_that_met_its_gate_is_not_told_to_do_more(self):
        """A caller handed "do this next" about a finished run would act on an
        instruction it did not ask for.

        The first version of this test rested on a run that *passed with a
        declared section missing*, which is how the weighted score behaved.
        P1.1 box three removed that: a section the route declared is now a
        criterion, and an answer missing one does not pass. The invariant is
        unchanged and the fixture is now a run that genuinely met everything.
        """
        output = (
            "# Svar\n\n" + ("innehåll " * 60) + "\n\n## Recommendation\nx\n\n"
            "## Next step\ny\n\n## Confidence\nHög.\n"
        )
        run = AtlasController(
            max_iterations=1, model_adapter=_ScriptedAdapter(output)
        ).run("hej", json_mode=True)

        self.assertEqual(run["stop_reason"], "passed")
        self.assertEqual(run["evaluations"][-1]["unmet_criteria"], [])
        self.assertIsNone(run["evaluations"][-1]["next_action"])

    def test_the_prose_is_still_there_for_a_human(self):
        """Structured feedback replaces parsing prose, not the prose itself."""
        run = self._run(self._output(block=False), max_iterations=2)

        self.assertTrue(run["evaluations"][0]["suggested_adjustment"])
        self.assertIsNotNone(run["evaluations"][0]["next_action"])

    def test_every_kind_is_in_the_published_vocabulary(self):
        from atlas_core.state import NEXT_ACTION_KINDS

        run = self._run(self._output(block=False))

        self.assertIn(self._action(run)["kind"], NEXT_ACTION_KINDS)


class TestARetryHasToBeWorthIt(_Repo):
    """Bounded runs only, which is where #29 put the identical-output rule.

    The unbudgeted path keeps its verdict semantics deliberately — see the note
    in `controller.py` — so a legacy run that exhausts its passes on a gap
    another producer could have closed still reports `max_iterations`.
    """

    LIMITS = RunLimits(
        wall_seconds=30, model_calls=5, tool_calls=0, tokens=100, output_bytes=200_000
    )

    def _bounded(self, adapter: Any, max_iterations: int = 3) -> dict[str, Any]:
        return AtlasController(
            max_iterations=max_iterations, model_adapter=adapter
        ).run(REPO_TASK, evidence=self.base, json_mode=True, limits=self.LIMITS)

    def test_the_same_failure_twice_ends_the_run(self):
        """Reworded, and wrong in exactly the same way.

        Byte equality would not catch this: the two answers differ. The gap
        they leave does not, so a third pass buys nothing.
        """
        first = self._output(block=False)
        second = self._output(block=False) + "\nEn extra rad som inte ändrar något.\n"
        adapter = _ScriptedAdapter(first, second)

        run = self._bounded(adapter)

        self.assertEqual(run["stop_reason"], "no_progress")
        self.assertEqual(run["metadata"]["no_progress"]["reason"], "unchanged_feedback")
        self.assertEqual(adapter.calls, 2)
        self.assertEqual(run["iteration"], 2)

    def test_byte_identical_output_keeps_its_own_reason(self):
        """The narrower rule from #29 still names itself."""
        adapter = _ScriptedAdapter(self._output(block=False))

        run = self._bounded(adapter)

        self.assertEqual(run["stop_reason"], "no_progress")
        self.assertEqual(
            run["metadata"]["no_progress"]["reason"], "identical_model_output"
        )

    def test_a_pass_that_moves_the_failure_still_gets_another_iteration(self):
        """Negative control. A gate that stops everything proves nothing."""
        first = self._output(block=False, sections=False)
        second = self._output(block=False)
        adapter = _ScriptedAdapter(first, second)

        run = self._bounded(adapter, max_iterations=2)

        self.assertEqual(adapter.calls, 2)
        self.assertNotEqual(run["stop_reason"], "no_progress")

    def test_an_unbudgeted_run_keeps_its_legacy_verdict(self):
        """Out of scope on purpose, and asserted so the boundary is visible."""
        run = AtlasController(
            max_iterations=2, model_adapter=_ScriptedAdapter(self._output(block=False))
        ).run(REPO_TASK, evidence=self.base, json_mode=True)

        self.assertEqual(run["stop_reason"], "max_iterations")


if __name__ == "__main__":
    unittest.main()
