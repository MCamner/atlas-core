"""P1.1: a source read in part says so, and absence says how far it looked.

Found by running the loop against a real repository (`docs/pinned-repo-review.md`).
`DEFAULT_MAX_LINES` is 80; the file whose gate invocations mattered is 169
lines and carries them on lines 104-138. A `source_lacks_literal` claim there
is settled `verified` against the excerpt, and the rendered sentence does name
its range — `lines 1-80 do not contain ...` — so the document never lied. It is
still a sentence a reader summarises into "the gate does not run pytest", which
is false of the file.

The asymmetry is the whole point, and it is why this is not fixed by refusing
the verdict. `source_contains_literal` over an excerpt is exactly as strong as
over a whole file: the text was found, and more text elsewhere cannot unfind
it. Absence is only ever as wide as what was searched.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from atlas_core.claim_check import ClaimKind, ClaimResult, TypedClaim, check_typed_claim
from atlas_core.finalizer import render_run_text
from atlas_core.finding import EvidenceRef, Finding
from atlas_core.observation import Observation
from atlas_core.snapshot import collect_observation, take_snapshot

SHORT = "alpha\nbeta\ngamma\n"
LONG = "".join(f"line {n}\n" for n in range(1, 121)) + "needle\n"


class _Repo(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (self.root / "short.txt").write_text(SHORT, encoding="utf-8")
        (self.root / "long.txt").write_text(LONG, encoding="utf-8")
        self.snapshot = take_snapshot(self.root)

    def _settle(self, observation: Observation, kind: ClaimKind, text: str):
        typed = TypedClaim(kind=kind, source_id=observation.source_id, text=text)
        ref = EvidenceRef(
            source_id=observation.source_id,
            content_sha256=observation.content_sha256,
            line_start=1,
            line_end=1,
            quoted=observation.excerpt.splitlines()[0],
        )
        finding = Finding.create(
            claim=typed.render(
                observation.path, observation.line_start, observation.line_end
            ),
            scope=observation.path,
            severity="P2",
            severity_rationale="Fixtur.",
            evidence=[ref],
        )
        return check_typed_claim(finding, typed, [observation], self.root)


class TestAnObservationKnowsHowMuchItIs(_Repo):
    def test_a_short_file_is_read_in_full(self):
        observation = collect_observation(self.snapshot, "short.txt")

        self.assertEqual(observation.total_lines, 3)
        self.assertTrue(observation.read_in_full())

    def test_a_long_file_is_not(self):
        observation = collect_observation(self.snapshot, "long.txt")

        self.assertEqual(observation.total_lines, 121)
        self.assertEqual(observation.line_end, 80)
        self.assertFalse(observation.read_in_full())

    def test_raising_the_bound_closes_it(self):
        """The other way out: read the whole thing."""
        observation = collect_observation(self.snapshot, "long.txt", max_lines=500)

        self.assertTrue(observation.read_in_full())

    def test_an_uncounted_source_says_it_does_not_know(self):
        """Three values, not two. "Not checked" is not "no"."""
        observation = collect_observation(self.snapshot, "short.txt")
        blind = Observation.create(
            source_type=observation.source_type,
            path=observation.path,
            collected_at=observation.collected_at,
            content_sha256=observation.content_sha256,
            excerpt=observation.excerpt,
            line_start=observation.line_start,
            line_end=observation.line_end,
            snapshot_id=observation.snapshot_id,
        )

        self.assertIsNone(blind.total_lines)
        self.assertIsNone(blind.read_in_full())

    def test_a_count_that_contradicts_the_range_is_refused(self):
        observation = collect_observation(self.snapshot, "long.txt")

        with self.assertRaises(ValueError):
            Observation.create(
                source_type=observation.source_type,
                path=observation.path,
                collected_at=observation.collected_at,
                content_sha256=observation.content_sha256,
                excerpt=observation.excerpt,
                line_start=observation.line_start,
                line_end=observation.line_end,
                snapshot_id=observation.snapshot_id,
                total_lines=10,
            )

    def test_it_is_in_the_exported_record(self):
        exported = collect_observation(self.snapshot, "long.txt").to_dict()

        self.assertEqual(exported["total_lines"], 121)
        self.assertIs(exported["read_in_full"], False)


class TestAbsenceSaysHowFarItLooked(_Repo):
    def test_a_lacks_verdict_over_a_partial_read_states_the_extent(self):
        """`needle` is on line 121. The excerpt stops at 80."""
        observation = collect_observation(self.snapshot, "long.txt")

        verdict = self._settle(observation, ClaimKind.LACKS, "needle")

        # Still verified: it *is* absent from lines 1-80, and the claim says so.
        self.assertEqual(verdict.result, ClaimResult.VERIFIED)
        self.assertIn("Only lines 1-80 of 121 were read", verdict.reason)
        self.assertIn("not from the source", verdict.reason)
        assert verdict.checked is not None
        self.assertIs(verdict.checked["read_in_full"], False)
        self.assertEqual(verdict.checked["total_lines"], 121)

    def test_a_lacks_verdict_over_a_whole_file_says_nothing_extra(self):
        """Negative control: the note must mean something when it appears."""
        observation = collect_observation(self.snapshot, "short.txt")

        verdict = self._settle(observation, ClaimKind.LACKS, "needle")

        self.assertEqual(verdict.result, ClaimResult.VERIFIED)
        self.assertNotIn("were read", verdict.reason)
        assert verdict.checked is not None
        self.assertIs(verdict.checked["read_in_full"], True)

    def test_a_contains_verdict_is_not_weakened_by_a_partial_read(self):
        """The asymmetry, asserted. Finding text is finding text."""
        observation = collect_observation(self.snapshot, "long.txt")

        verdict = self._settle(observation, ClaimKind.CONTAINS, "line 12")

        self.assertEqual(verdict.result, ClaimResult.VERIFIED)
        self.assertNotIn("were read", verdict.reason)


class TestTheTrailerSaysItToo(_Repo):
    """The document already said it; the prose a human reads is where the
    summarising happens."""

    def _evaluation(self, kind: ClaimKind, path: str, full: bool) -> dict:
        return {
            "passed": False,
            "quality_score": 0.5,
            "score_method": "criteria_met_share",
            "unmet_criteria": [],
            "met_criteria": [],
            "evidence_gaps": [],
            "requires_user_approval": False,
            "citation_checks": [
                {
                    "verdict": "verified",
                    "claim_check": {
                        "checked": {
                            "kind": kind.value,
                            "path": path,
                            "read_in_full": full,
                        }
                    },
                }
            ],
        }

    def _run(self, evaluation: dict) -> str:
        return render_run_text(
            {
                "task": "x",
                "route": {"name": "repo_review"},
                "iteration": 1,
                "max_iterations": 1,
                "stop_reason": "insufficient_evidence",
                "outputs": ["Ett svar."],
                "evaluations": [evaluation],
            }
        )

    def test_a_partial_absence_is_named(self):
        text = self._run(
            self._evaluation(ClaimKind.LACKS, "release-check.sh", full=False)
        )

        self.assertIn("Absence was established only over the lines read", text)
        self.assertIn("release-check.sh", text)

    def test_a_whole_file_absence_is_not(self):
        text = self._run(
            self._evaluation(ClaimKind.LACKS, "release-check.sh", full=True)
        )

        self.assertNotIn("Absence was established", text)

    def test_a_contains_claim_never_raises_it(self):
        text = self._run(
            self._evaluation(ClaimKind.CONTAINS, "release-check.sh", full=False)
        )

        self.assertNotIn("Absence was established", text)


if __name__ == "__main__":
    unittest.main()
