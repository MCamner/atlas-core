"""P0.1 box two: a run that reads a state must notice when that state moves.

`take_snapshot`, `verify_observation` and `detect_drift` have existed since
#16, and nothing called them from a run. That left the box half closed: the
loop could tell that a *cited* source had moved, because checking a citation
re-reads it, and it could not tell that the ground under the run had moved for
any other reason — a branch switched mid-run, or a source nobody happened to
cite changed while the model was thinking.

The gate closes that. It runs twice: once before the first iteration, so a run
does not spend a model call on a state that has already moved, and once before
each grading, so claims are never graded against a state that no longer holds.
A run that drifts stops `blocked`, which the state machine classifies as
`control` — the ground moved, the answer was not judged wrong.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any

from atlas_core import AtlasController, StubModelAdapter
from atlas_core.adapters.model import ModelResult
from atlas_core.evidence import FINDINGS_FENCE
from atlas_core.evidence_base import EvidenceBase
from atlas_core.machine import spec_for
from atlas_core.snapshot import collect_observation, take_snapshot

README = "# Atlas Core\n\npip install atlas-core\n\nEn avgränsad loop-motor.\n"
NOTES = "Anteckningar som ingen citerar.\n"

PROSE = """# Repogranskning

Granskningen nedan bygger på de källor som lästes denna körning och går igenom
repots dokumentation, testupplägg och släppprocess i tillräcklig detalj för att
motivera de slutsatser som dras. Texten är avsiktligt lång nog för att passera
substanskravet, eftersom poängen här är vad som händer med marken under foten.

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


class _Base(unittest.TestCase):
    """A real snapshot over a real git repo, and two observations.

    `notes.md` is observed and never cited on purpose: it is the source whose
    drift nothing else in the system would notice.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (self.root / "README.md").write_text(README, encoding="utf-8")
        (self.root / "notes.md").write_text(NOTES, encoding="utf-8")
        self._git("init", "-q")
        self._git("config", "user.email", "test@example.com")
        self._git("config", "user.name", "Test")
        self._git("add", "-A")
        self._git("commit", "-qm", "first")
        self.snapshot = take_snapshot(self.root)
        self.readme = collect_observation(self.snapshot, "README.md")
        self.notes = collect_observation(self.snapshot, "notes.md")
        self.base = EvidenceBase(
            snapshot=self.snapshot, observations=[self.readme, self.notes]
        )

    def _resnapshot(self) -> None:
        """Re-take the snapshot, so a test can choose the state it starts from."""
        self.snapshot = take_snapshot(self.root)
        self.readme = collect_observation(self.snapshot, "README.md")
        self.notes = collect_observation(self.snapshot, "notes.md")
        self.base = EvidenceBase(
            snapshot=self.snapshot, observations=[self.readme, self.notes]
        )

    def _git(self, *args: str) -> None:
        subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True)

    def _output(self) -> str:
        """A finding that passes on its own merits, so the gate is what stops it.

        The claim text is rendered from the typed claim, which is what lets a
        verdict be reached at all: the sentence may not say more than what was
        tested.
        """
        from atlas_core.claim_check import ClaimKind, TypedClaim

        typed = TypedClaim(
            kind=ClaimKind.CONTAINS,
            source_id=self.readme.source_id,
            text="# Atlas Core",
        )
        claim = typed.render(
            self.readme.path, self.readme.line_start, self.readme.line_end
        )
        finding: dict[str, Any] = {
            "claim": claim,
            "scope": "README.md",
            "severity": "P1",
            "severity_rationale": "Blockerar en ny användare.",
            "evidence": [
                {
                    "source_id": self.readme.source_id,
                    "content_sha256": self.readme.content_sha256,
                    "line_start": 1,
                    "line_end": 1,
                    "quoted": "# Atlas Core",
                }
            ],
            "typed_claim": {
                "kind": typed.kind.value,
                "source_id": typed.source_id,
                "text": typed.text,
            },
        }
        fence = "```" + FINDINGS_FENCE
        return (
            PROSE.format(claim=claim) + "\n" + fence + "\n" + json.dumps([finding]) + "\n```\n"
        )

    def _run(self, adapter: Any = None, *, evidence: bool = True) -> dict[str, Any]:
        controller = AtlasController(
            max_iterations=1, model_adapter=adapter or StubModelAdapter(self._output())
        )
        return controller.run(
            "granska repo",
            evidence=self.base if evidence else None,
            json_mode=True,
        )


class TestTheGateStopsADriftedRun(_Base):
    def test_a_source_nobody_cites_still_stops_the_run(self):
        """The case citation checking cannot see.

        `check_finding` re-reads what a finding points at, so a cited source
        that moves is already caught. Nothing looked at the rest of what the
        run read, and a review resting on an unchanged README while its notes
        were rewritten underneath is resting on a state that no longer exists.
        """
        (self.root / "notes.md").write_text("helt annat innehåll\n", encoding="utf-8")

        run = self._run()

        self.assertEqual(run["stop_reason"], "blocked")
        self.assertIn(self.notes.source_id, run["metadata"]["drift"]["not_evidence"])

    def test_content_drift_is_caught_where_the_state_check_is_blind(self):
        """Why the gate pairs two checks instead of trusting the state.

        `has_moved` compares HEAD and clean/dirty. A worktree that was already
        dirty when the snapshot was taken stays dirty at the same commit when a
        file changes again, so the state looks unmoved while the bytes a claim
        rests on have been rewritten. The per-source content check is what sees
        it, and the record says so: `head_moved` is false and the source is
        listed anyway.
        """
        (self.root / "pending.md").write_text("osparat arbete\n", encoding="utf-8")
        self._resnapshot()
        (self.root / "notes.md").write_text("helt annat innehåll\n", encoding="utf-8")

        drift = self._run()["metadata"]["drift"]

        entry = drift["not_evidence"][self.notes.source_id]
        self.assertEqual(entry["result"], "stale")
        self.assertFalse(drift["head_moved"])
        self.assertIn(self.notes.path, drift["paths"])

    def test_a_vanished_source_stops_the_run_too(self):
        (self.root / "notes.md").unlink()

        run = self._run()

        self.assertEqual(run["stop_reason"], "blocked")
        self.assertEqual(
            run["metadata"]["drift"]["not_evidence"][self.notes.source_id]["result"],
            "missing",
        )

    def test_a_moved_head_stops_the_run(self):
        """The literal requirement: a changed HEAD during the read.

        Content alone would not catch this. Committing leaves every observed
        file byte-identical; what moved is which state the run claims to have
        read, and mixing a branch into a review of another one is exactly what
        the box says not to do.
        """
        (self.root / "extra.md").write_text("ny fil\n", encoding="utf-8")
        self._git("add", "-A")
        self._git("commit", "-qm", "second")

        run = self._run()

        self.assertEqual(run["stop_reason"], "blocked")
        self.assertTrue(run["metadata"]["drift"]["head_moved"])

    def test_switching_to_a_branch_with_other_content_stops_the_run(self):
        """"Blanda inte main och arbetsgren": the run refuses to."""
        self._git("checkout", "-q", "-b", "arbetsgren")
        (self.root / "README.md").write_text("# Annat\n", encoding="utf-8")
        self._git("commit", "-qam", "annat innehåll")

        run = self._run()

        self.assertEqual(run["stop_reason"], "blocked")
        self.assertTrue(run["metadata"]["drift"]["head_moved"])

    def test_a_branch_label_at_the_same_commit_is_not_drift(self):
        """Where the line sits, stated rather than left to be discovered.

        A second name for the commit the run read changes no byte it relies
        on, so refusing here would be a false alarm. Separation is kept by
        recording which ref was read — the manifest carries it — and by
        `EvidenceBase` refusing observations from more than one snapshot.
        """
        self._git("checkout", "-q", "-b", "arbetsgren")

        run = self._run()

        self.assertNotEqual(run["stop_reason"], "blocked")
        self.assertEqual(run["evidence_manifest"]["snapshot"]["ref"], self.snapshot.ref)

    def test_blocked_is_a_control_stop_not_a_verdict_on_the_answer(self):
        """The ground moved. That is not the same as the answer being wrong."""
        (self.root / "notes.md").write_text("annat\n", encoding="utf-8")

        run = self._run()

        self.assertEqual(run["stop_class"], "control")
        self.assertEqual(spec_for("blocked").exit_code, 2)


class TestTheGradeSurvivesTheStop(_Base):
    """The gate runs after grading, and that is a deliberate choice.

    Refusing before the model call would save the call. It would also throw
    away the per-finding record that says *which* claim rested on what moved,
    which is what a reader has to act on, and it would fire or not depending on
    whether the root happens to be a git checkout — an edit there also flips
    clean to dirty. One gate, after grading, keeps one rule and loses nothing:
    the grade is history, the run is `blocked`.
    """

    def test_the_answer_is_still_graded_and_the_record_kept(self):
        (self.root / "notes.md").write_text("annat\n", encoding="utf-8")

        run = self._run()

        self.assertEqual(run["stop_reason"], "blocked")
        self.assertEqual(len(run["evaluations"]), 1)
        self.assertTrue(run["evaluations"][0]["citation_checks"])

    def test_a_graded_pass_does_not_become_the_run_outcome(self):
        """The README is untouched, so every citation still checks out.

        This is the case that would read as a clean pass if the gate only
        looked at what was cited: the finding is sound, and the run read a
        state that no longer exists.
        """
        (self.root / "notes.md").write_text("annat\n", encoding="utf-8")

        run = self._run()

        self.assertTrue(run["evaluations"][0]["passed"])
        self.assertEqual(run["stop_reason"], "blocked")
        self.assertEqual(run["stop_class"], "control")

    def test_drift_during_the_model_call_is_caught(self):
        """The window that matters is the long one.

        A provider call is where a run spends its time, so it is where a branch
        switch or an edit is most likely to land. The observations were fresh
        when the run started.
        """

        class _MutatingAdapter:
            def __init__(self, output: str, root: Path):
                self.output = output
                self.root = root
                self.calls = 0

            def execute(self, **kwargs: Any) -> ModelResult:
                self.calls += 1
                (self.root / "notes.md").write_text("ändrad under körning\n", encoding="utf-8")
                return ModelResult(output=self.output, provider="stub", model="stub")

        adapter = _MutatingAdapter(self._output(), self.root)

        run = self._run(adapter)

        self.assertEqual(adapter.calls, 1)
        self.assertEqual(run["stop_reason"], "blocked")
        self.assertIn(self.notes.source_id, run["metadata"]["drift"]["not_evidence"])

    def test_the_text_says_the_ground_moved(self):
        """A trailer that reads "Status: passed" beside a blocked run is a trap."""
        (self.root / "notes.md").write_text("annat\n", encoding="utf-8")
        controller = AtlasController(
            max_iterations=1, model_adapter=StubModelAdapter(self._output())
        )

        text = controller.run("granska repo", evidence=self.base)

        self.assertIn("Stop reason: blocked", text)
        self.assertIn("notes.md", text.split("---")[-1])


class TestTheGateIsNotUnconditional(_Base):
    """Negative controls. A gate that stops everything proves nothing."""

    def test_an_unchanged_state_grades_as_before(self):
        run = self._run()

        self.assertNotEqual(run["stop_reason"], "blocked")
        self.assertTrue(run["evaluations"])
        self.assertNotIn("drift", run["metadata"])

    def test_a_run_without_an_evidence_base_is_untouched(self):
        """Prose context cannot be re-read, so there is nothing to check."""
        (self.root / "notes.md").write_text("annat\n", encoding="utf-8")

        run = self._run(evidence=False)

        self.assertNotEqual(run["stop_reason"], "blocked")
        self.assertNotIn("drift", run["metadata"])


if __name__ == "__main__":
    unittest.main()
