"""P0.1b: snapshots and collection — bind an observation to what it read.

ROADMAP.md P0.1, second box. The Definition of Done for this phase is a
sequence, and `TestDefinitionOfDone` walks it end to end:

    1. Read README.md at a given snapshot.
    2. Create Observation.v1 with provenance.
    3. Read the same source again.
    4. Check content hash and line range.
    5. Detect whether the content changed.
    6. Return STALE on mismatch.
    7. Never allow STALE as verified evidence.

Step 7 is the one that matters. Everything else is machinery for it.

Still not wired into the controller: the loop keeps taking `list[str]`
observations. Collection here is a separate, testable layer, and connecting the
two is its own change.
"""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from atlas_core.observation import UNKNOWN, Observation
from atlas_core.snapshot import (
    Snapshot,
    Verification,
    collect_observation,
    detect_drift,
    take_snapshot,
    verify_all,
    verify_observation,
)

README = "# Demo repo\n\nEtt litet repo.\nRad fyra.\nRad fem.\n"

HAS_GIT = shutil.which("git") is not None


class _Repo(unittest.TestCase):
    """A throwaway directory, optionally a git repo."""

    git = False

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        (self.root / "README.md").write_text(README, encoding="utf-8")
        if self.git:
            self._git("init", "-q")
            self._git("config", "user.email", "t@example.com")
            self._git("config", "user.name", "Test")
            self._git("add", "README.md")
            self._git("commit", "-qm", "init")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _git(self, *args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=self.tmp, capture_output=True, text=True, check=False
        ).stdout.strip()


class TestSnapshotProvenance(_Repo):
    def test_a_plain_directory_reports_unknown_rather_than_guessing(self):
        """No git, no commit. Say so instead of inventing one."""
        snapshot = take_snapshot(self.root)

        self.assertEqual(snapshot.commit, UNKNOWN)
        self.assertEqual(snapshot.ref, UNKNOWN)
        self.assertEqual(snapshot.worktree_state, UNKNOWN)
        self.assertTrue(snapshot.snapshot_id)

    def test_snapshot_id_is_derived_not_random(self):
        """Two snapshots of the same unchanged state are the same snapshot."""
        self.assertEqual(take_snapshot(self.root).snapshot_id, take_snapshot(self.root).snapshot_id)

    def test_different_roots_are_different_snapshots(self):
        other = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, other, True)

        self.assertNotEqual(
            take_snapshot(self.root).snapshot_id, take_snapshot(other).snapshot_id
        )


@unittest.skipUnless(HAS_GIT, "git not available")
class TestGitSnapshotProvenance(_Repo):
    git = True

    def test_a_clean_checkout_reports_its_commit_and_ref(self):
        snapshot = take_snapshot(self.root)

        self.assertRegex(snapshot.commit, r"^[0-9a-f]{40}$")
        self.assertNotEqual(snapshot.ref, UNKNOWN)
        self.assertEqual(snapshot.worktree_state, "clean")

    def test_an_uncommitted_change_makes_the_worktree_dirty(self):
        (self.root / "README.md").write_text(README + "ändrad\n", encoding="utf-8")
        snapshot = take_snapshot(self.root)

        self.assertEqual(snapshot.worktree_state, "dirty")

    def test_a_dirty_snapshot_does_not_let_commit_stand_for_content(self):
        """Design decision 1, end to end through collection."""
        (self.root / "README.md").write_text(README + "ändrad\n", encoding="utf-8")
        observation = collect_observation(take_snapshot(self.root), "README.md")

        self.assertNotEqual(observation.commit, UNKNOWN)
        self.assertFalse(observation.commit_identifies_content())
        self.assertTrue(observation.is_verifiable())

    def test_a_clean_snapshot_lets_commit_identify_content(self):
        observation = collect_observation(take_snapshot(self.root), "README.md")

        self.assertTrue(observation.commit_identifies_content())

    def test_switching_branch_is_a_different_snapshot(self):
        """"Blanda inte main och arbetsgren utan tydlig separation." """
        before = take_snapshot(self.root)
        self._git("checkout", "-qb", "work")
        (self.root / "README.md").write_text(README + "på grenen\n", encoding="utf-8")
        self._git("commit", "-qam", "work")
        after = take_snapshot(self.root)

        self.assertNotEqual(before.commit, after.commit)
        self.assertNotEqual(before.snapshot_id, after.snapshot_id)

    def test_a_moved_head_is_detected(self):
        """"Upptäck ändrad HEAD/fil under läsning." """
        snapshot = take_snapshot(self.root)
        self.assertFalse(snapshot.has_moved())

        (self.root / "README.md").write_text(README + "efteråt\n", encoding="utf-8")
        self.assertTrue(snapshot.has_moved())


class TestCollection(_Repo):
    def test_collection_hashes_full_content_not_the_excerpt(self):
        """Design decision 2: trimming the excerpt cannot move the hash."""
        whole = collect_observation(take_snapshot(self.root), "README.md")
        trimmed = collect_observation(take_snapshot(self.root), "README.md", max_lines=2)

        self.assertEqual(whole.content_sha256, trimmed.content_sha256)
        self.assertNotEqual(whole.excerpt, trimmed.excerpt)
        self.assertEqual(trimmed.line_end, 2)

    def test_the_excerpt_declares_the_lines_it_covers(self):
        observation = collect_observation(take_snapshot(self.root), "README.md", max_lines=3)

        self.assertEqual((observation.line_start, observation.line_end), (1, 3))
        self.assertEqual(observation.excerpt, "# Demo repo\n\nEtt litet repo.")

    def test_a_missing_file_is_not_an_observation(self):
        with self.assertRaises(FileNotFoundError):
            collect_observation(take_snapshot(self.root), "saknas.md")

    def test_collected_observations_carry_the_snapshot(self):
        snapshot = take_snapshot(self.root)
        observation = collect_observation(snapshot, "README.md")

        self.assertEqual(observation.snapshot_id, snapshot.snapshot_id)
        self.assertEqual(observation.source_type, "local_file")


class TestVerification(_Repo):
    def test_an_unchanged_source_verifies_fresh(self):
        snapshot = take_snapshot(self.root)
        observation = collect_observation(snapshot, "README.md")

        result = verify_observation(observation, self.root)

        self.assertEqual(result.result, "fresh")
        self.assertTrue(result.is_evidence())

    def test_changed_content_is_stale(self):
        snapshot = take_snapshot(self.root)
        observation = collect_observation(snapshot, "README.md")
        (self.root / "README.md").write_text(README + "ändrad\n", encoding="utf-8")

        result = verify_observation(observation, self.root)

        self.assertEqual(result.result, "stale")
        self.assertIn("content", result.reason)

    def test_a_changed_line_range_is_stale_even_when_the_file_is_the_same_size(self):
        """The excerpt has to still be what was quoted, not merely plausible."""
        snapshot = take_snapshot(self.root)
        observation = collect_observation(snapshot, "README.md", max_lines=2)
        swapped = README.replace("# Demo repo", "# Annat repo")
        (self.root / "README.md").write_text(swapped, encoding="utf-8")

        result = verify_observation(observation, self.root)

        self.assertEqual(result.result, "stale")

    def test_a_deleted_source_is_missing_not_fresh(self):
        snapshot = take_snapshot(self.root)
        observation = collect_observation(snapshot, "README.md")
        (self.root / "README.md").unlink()

        result = verify_observation(observation, self.root)

        self.assertEqual(result.result, "missing")
        self.assertFalse(result.is_evidence())

    def test_an_observation_without_a_digest_cannot_be_verified(self):
        observation = Observation.create(
            source_type="local_file",
            path="README.md",
            snapshot_id="snap-1",
            collected_at="2026-09-20T09:00:00+00:00",
            content_sha256=UNKNOWN,
            excerpt="# Demo repo",
            line_start=1,
            line_end=1,
        )

        result = verify_observation(observation, self.root)

        self.assertEqual(result.result, "unverifiable")
        self.assertFalse(result.is_evidence())

    def test_only_fresh_counts_as_evidence(self):
        """Step 7. The whole phase is here."""
        for outcome in ("stale", "missing", "unverifiable"):
            with self.subTest(result=outcome):
                self.assertFalse(
                    Verification(result=outcome, reason="", observed_sha256=UNKNOWN).is_evidence()
                )

        self.assertTrue(
            Verification(result="fresh", reason="", observed_sha256="a" * 64).is_evidence()
        )


class TestDriftDuringARead(_Repo):
    """"Upptäck ändrad HEAD/fil under läsning."

    Two mechanisms, because one is not enough. `has_moved` sees HEAD and
    clean/dirty; content drift needs the per-source check.
    """

    def test_a_consistent_read_reports_no_drift(self):
        snapshot = take_snapshot(self.root)
        observations = [collect_observation(snapshot, "README.md")]

        report = detect_drift(snapshot, observations)

        self.assertTrue(report.is_consistent())
        self.assertEqual(report.not_evidence, {})

    def test_a_file_changing_mid_read_is_drift(self):
        snapshot = take_snapshot(self.root)
        observations = [collect_observation(snapshot, "README.md")]
        (self.root / "README.md").write_text(README + "under läsning\n", encoding="utf-8")

        report = detect_drift(snapshot, observations)

        self.assertFalse(report.is_consistent())
        self.assertEqual(
            [v.result for v in report.not_evidence.values()], ["stale"]
        )

    @unittest.skipUnless(HAS_GIT, "git not available")
    def test_drift_is_caught_even_when_has_moved_cannot_see_it(self):
        """The limit `has_moved` has, and the reason detect_drift exists.

        An already-dirty worktree changing again stays dirty at the same
        commit, so the state check reports nothing. The content check does.
        """
        self._git("init", "-q")
        self._git("config", "user.email", "t@example.com")
        self._git("config", "user.name", "Test")
        self._git("add", "README.md")
        self._git("commit", "-qm", "init")
        (self.root / "README.md").write_text(README + "redan smutsig\n", encoding="utf-8")

        snapshot = take_snapshot(self.root)
        self.assertEqual(snapshot.worktree_state, "dirty")
        observations = [collect_observation(snapshot, "README.md")]

        (self.root / "README.md").write_text(README + "ändrad igen\n", encoding="utf-8")

        self.assertFalse(snapshot.has_moved(), "state check cannot see this")
        self.assertFalse(detect_drift(snapshot, observations).is_consistent())

    def test_verify_all_is_keyed_by_source_id(self):
        snapshot = take_snapshot(self.root)
        observation = collect_observation(snapshot, "README.md")

        results = verify_all([observation], self.root)

        self.assertEqual(list(results), [observation.source_id])


class TestDefinitionOfDone(_Repo):
    """The seven steps, in order, as one reproducible sequence."""

    def test_the_p0_1_definition_of_done(self):
        # 1. Read README.md at a given snapshot.
        snapshot = take_snapshot(self.root)

        # 2. Create Observation.v1 with provenance.
        observation = collect_observation(snapshot, "README.md", max_lines=3)
        self.assertEqual(observation.snapshot_id, snapshot.snapshot_id)
        self.assertTrue(observation.is_verifiable())

        # 3 + 4. Read the same source again and check hash and line range.
        first = verify_observation(observation, self.root)
        self.assertEqual(first.result, "fresh")
        self.assertEqual(first.observed_sha256, observation.content_sha256)

        # 5. Detect whether the content changed.
        (self.root / "README.md").write_text(
            README.replace("Ett litet repo.", "Något helt annat."), encoding="utf-8"
        )

        # 6. Return STALE on mismatch.
        second = verify_observation(observation, self.root)
        self.assertEqual(second.result, "stale")
        self.assertNotEqual(second.observed_sha256, observation.content_sha256)

        # 7. Never allow STALE as verified evidence.
        self.assertFalse(second.is_evidence())

    def test_the_sequence_is_reproducible(self):
        """Same directory, same state, same answers."""
        snapshot = take_snapshot(self.root)
        a = collect_observation(snapshot, "README.md")
        b = collect_observation(take_snapshot(self.root), "README.md")

        self.assertEqual(a.source_id, b.source_id)
        self.assertEqual(a.content_sha256, b.content_sha256)
        self.assertEqual(a.excerpt, b.excerpt)


if __name__ == "__main__":
    unittest.main()
