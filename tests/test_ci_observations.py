"""P0.2, box four: a CI result that can be cited, and can go stale.

ROADMAP.md P0.2 lists `stale CI` among the cases that must not pass. Until now
`ci` was a declared `SourceType` that nothing produced, so any CI citation was
refused as `unsupported_source_type`. A review named that for what it was:
refusing a source because nobody can fetch it is not the same as testing what
happens when a fetched one goes out of date.

So a CI run is now collectible, with provenance, and re-read through its
adapter. That makes the fresh case usable — which is what gives the stale case
something to mean.
"""

import json
import shutil
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from typing import Any

from atlas_core import AtlasController, EvidenceBase, StubModelAdapter
from atlas_core.ci import (
    CIRun,
    StubCIAdapter,
    ci_readers,
    collect_ci_observation,
)
from atlas_core.claim_check import ClaimKind, TypedClaim
from atlas_core.evidence import FINDINGS_FENCE
from atlas_core.finding import EvidenceStatus, check_finding, resolve_readers
from atlas_core.observation import UNKNOWN
from atlas_core.snapshot import collect_observation, take_snapshot

GREEN = CIRun(
    provider="github",
    workflow="test",
    run_id="35516241968",
    ref="main",
    commit="b8acc81",
    conclusion="success",
    completed_at="2026-09-20T14:21:46+00:00",
)

RED = replace(GREEN, run_id="35516241999", conclusion="failure")

README = "# Atlas Core\n\npip install atlas-core\n"


class _Run(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        (self.root / "README.md").write_text(README, encoding="utf-8")
        self.snapshot = take_snapshot(self.root)
        self.adapter = StubCIAdapter(GREEN)
        self.ci = collect_ci_observation(self.snapshot, self.adapter, "main")
        self.base = EvidenceBase(
            snapshot=self.snapshot,
            observations=[self.ci],
            readers=ci_readers(self.adapter),
        )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _finding(self, **extra: Any) -> dict[str, Any]:
        finding: dict[str, Any] = {
            "claim": "CI är grön.",
            "scope": "CI",
            "severity": "P1",
            "severity_rationale": "En röd CI blockerar release.",
            "evidence": [
                {
                    "source_id": self.ci.source_id,
                    "content_sha256": self.ci.content_sha256,
                    "line_start": 1,
                    "line_end": 1,
                    "quoted": self.ci.excerpt,
                }
            ],
        }
        finding.update(extra)
        return finding

    def _run(self, findings: list[dict[str, Any]]) -> Any:
        fence = "```" + FINDINGS_FENCE
        output = f"""# Granskning

Genomgången nedan bygger på de källor som lästes denna körning och täcker
byggstatus och släppprocess i tillräcklig detalj för att motivera slutsatserna.
Texten är lång nog för att passera substanskravet i evalueringen.

## Observed sources
- CI

## Findings
- {findings[0]["claim"]}

## Recommendation
Släpp inte förrän CI är grön.

## Next step
Kontrollera senaste körningen.

## Confidence
Medium.

{fence}
{json.dumps(findings)}
```
"""
        return AtlasController(
            max_iterations=1, model_adapter=StubModelAdapter(output)
        ).run("granska repo", evidence=self.base, json_mode=True)


class TestStaleCI(_Run):
    """The box's case: a green run cited, then re-run red."""

    def test_a_fresh_ci_citation_is_intact(self):
        """The control. Without this the stale case would prove nothing."""
        check = check_finding(
            _as_finding(self._finding()),
            [self.ci],
            self.root,
            readers=ci_readers(self.adapter),
        )

        self.assertEqual([status for _, status in check.statuses], [EvidenceStatus.INTACT])

    def test_a_ci_run_that_changed_after_it_was_observed_is_stale(self):
        """Someone re-ran the workflow. The citation still looks perfect."""
        self.adapter.set_run(RED)

        check = check_finding(
            _as_finding(self._finding()),
            [self.ci],
            self.root,
            readers=ci_readers(self.adapter),
        )

        self.assertEqual(
            [status for _, status in check.statuses], [EvidenceStatus.STALE_SOURCE]
        )
        self.assertFalse(check.citations_are_sound())

    def test_a_stale_ci_finding_cannot_pass_the_run(self):
        """Through `AtlasController`, which is where it has to hold."""
        self.adapter.set_run(RED)

        run = self._run([self._finding()])
        evaluation = run["evaluations"][-1]

        self.assertFalse(evaluation["passed"])
        self.assertIn("unsound_citations", evaluation["evidence_gaps"])
        self.assertEqual(
            evaluation["citation_checks"][0]["statuses"][0]["status"], "stale_source"
        )

    def test_the_same_conclusion_on_a_new_run_id_is_still_stale(self):
        """Identity is the run, not the verdict it happened to produce.

        A re-run that comes back green is a different run. Treating it as the
        same one would let a citation point at a run nobody looked at.
        """
        self.adapter.set_run(replace(GREEN, run_id="99999999"))

        check = check_finding(
            _as_finding(self._finding()),
            [self.ci],
            self.root,
            readers=ci_readers(self.adapter),
        )

        self.assertEqual(
            [status for _, status in check.statuses], [EvidenceStatus.STALE_SOURCE]
        )

    def test_the_source_is_refetched_rather_than_cached(self):
        """A cached copy would make every CI citation permanently fresh."""
        before = self.adapter.fetches

        check_finding(
            _as_finding(self._finding()),
            [self.ci],
            self.root,
            readers=ci_readers(self.adapter),
        )

        self.assertGreater(self.adapter.fetches, before)


class TestWithoutAReaderNothingIsAssumed(_Run):
    def test_a_ci_observation_with_no_reader_is_unsupported(self):
        """No adapter means the state cannot be established, not that it holds."""
        check = check_finding(_as_finding(self._finding()), [self.ci], self.root)

        self.assertEqual(
            [status for _, status in check.statuses],
            [EvidenceStatus.UNSUPPORTED_SOURCE_TYPE],
        )

    def test_a_supplied_reader_cannot_replace_the_local_file_reader(self):
        """It would own containment and freshness for every local citation."""

        class Liar:
            def read(self, observation: Any) -> str:
                return "vad som helst"

        readers = resolve_readers(self.root, {"local_file": Liar()})

        self.assertNotIsInstance(readers["local_file"], Liar)

    def test_a_reader_that_cannot_be_copied_does_not_break_the_run_document(self):
        """A host's reader may wrap a network client. Rendering must not copy it.

        `asdict` deep-copies as it walks, so clearing the evidence base after
        the walk would raise here instead of producing a document. Found by a
        negative control that this suite was missing.
        """

        class Unclonable:
            source_type = "ci"

            def __deepcopy__(self, memo: Any) -> Any:
                raise RuntimeError("a live client cannot be copied")

            def read(self, observation: Any) -> str:
                return ""

        controller = AtlasController(
            max_iterations=1, model_adapter=StubModelAdapter("x" * 400)
        )
        base = EvidenceBase(
            snapshot=self.snapshot,
            observations=[self.ci],
            readers={"ci": Unclonable()},
        )

        run = controller.run("granska repo", evidence=base, json_mode=True)

        self.assertNotIn("evidence_base", run)
        self.assertIsNotNone(run["evidence_manifest"])

    def test_the_base_knows_what_it_can_reread(self):
        local = collect_observation(self.snapshot, "README.md")
        bare = EvidenceBase(snapshot=self.snapshot, observations=[self.ci, local])

        self.assertTrue(bare.can_reread(local))
        self.assertFalse(bare.can_reread(self.ci))
        self.assertTrue(self.base.can_reread(self.ci))


class TestCIProvenance(_Run):
    def test_the_digest_covers_the_result_not_the_field_order(self):
        """A provider reordering its JSON must not read as drift."""
        same = CIRun(**{key: getattr(GREEN, key) for key in reversed(list(vars(GREEN)))})

        self.assertEqual(same.canonical(), GREEN.canonical())

    def test_a_changed_conclusion_changes_the_digest(self):
        self.assertNotEqual(RED.canonical(), GREEN.canonical())

    def test_only_success_is_green(self):
        for conclusion in ("failure", "cancelled", "timed_out", "in_progress", UNKNOWN):
            self.assertFalse(replace(GREEN, conclusion=conclusion).is_green(), conclusion)
        self.assertTrue(GREEN.is_green())

    def test_an_unfetchable_field_cannot_be_defaulted_into_a_green_result(self):
        for missing in ("provider", "workflow", "run_id", "ref", "commit"):
            with self.assertRaises(ValueError, msg=missing):
                replace(GREEN, **{missing: ""})

    def test_an_unknown_conclusion_is_refused(self):
        with self.assertRaises(ValueError):
            replace(GREEN, conclusion="probably fine")

    def test_the_observation_records_the_commit_it_ran_against(self):
        self.assertEqual(self.ci.commit, GREEN.commit)
        self.assertEqual(self.ci.ref, GREEN.ref)
        self.assertEqual(self.ci.path, "ci://github/test@main")

    def test_the_excerpt_is_what_the_digest_covers(self):
        self.assertEqual(self.ci.excerpt, GREEN.canonical())


class TestATypedClaimAboutCI(_Run):
    """The semantic layer reaches CI through the same reader."""

    def _typed(self, kind: ClaimKind, text: str) -> tuple[str, dict[str, Any]]:
        claim = TypedClaim(kind=kind, source_id=self.ci.source_id, text=text).render(
            self.ci.path, 1, 1
        )
        return claim, {
            "kind": kind.value,
            "source_id": self.ci.source_id,
            "text": text,
        }

    def test_a_true_claim_about_a_green_run_is_verified(self):
        claim, typed = self._typed(ClaimKind.CONTAINS, '"conclusion":"success"')

        run = self._run([self._finding(claim=claim, typed_claim=typed)])

        self.assertEqual(run["evaluations"][-1]["citation_checks"][0]["verdict"], "verified")
        self.assertTrue(run["evaluations"][-1]["passed"])

    def test_the_same_claim_after_a_red_rerun_is_stale_not_verified(self):
        """Staleness outranks the claim: the run it cites is not the run now."""
        claim, typed = self._typed(ClaimKind.CONTAINS, '"conclusion":"success"')
        self.adapter.set_run(RED)

        run = self._run([self._finding(claim=claim, typed_claim=typed)])
        record = run["evaluations"][-1]["citation_checks"][0]

        self.assertEqual(record["statuses"][0]["status"], "stale_source")
        self.assertNotEqual(record["verdict"], "verified")
        self.assertFalse(run["evaluations"][-1]["passed"])


def _as_finding(payload: dict[str, Any]) -> Any:
    from atlas_core.evidence import structured_findings

    parsed = structured_findings(
        "```" + FINDINGS_FENCE + "\n" + json.dumps([payload]) + "\n```"
    )
    assert parsed.malformed is None, parsed.malformed
    return parsed.findings[0]


if __name__ == "__main__":
    unittest.main()
