"""P0.1a: Observation.v1 — provenance with defined semantics.

ROADMAP.md P0.1, first box. The acceptance criterion for this PR is narrow and
specific: every provenance field has defined meaning, and **an unverifiable
field is never replaced by a plausible-looking value**. A fabricated commit SHA
is worse than an honest `unknown`, because the next phase will verify claims
against exactly these fields.

This PR is data only. Nothing here reads a file, and nothing is wired into the
controller yet; collection is PR B.
"""

import json
import unittest
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

from atlas_core.observation import (
    UNKNOWN,
    Observation,
    derive_source_id,
)

ROOT = Path(__file__).parents[1]

CONTENT = "# Demo repo\n\nEtt litet repo.\nRad fyra.\n"
SHA = "b5f2a1"  # not the real digest; these tests never assert the algorithm


def _observation(**overrides: object) -> Observation:
    fields: dict[str, object] = {
        "source_type": "local_file",
        "path": "README.md",
        "snapshot_id": "snap-1",
        "collected_at": "2026-09-20T09:00:00+00:00",
        "content_sha256": "a" * 64,
        "excerpt": "# Demo repo",
        "line_start": 1,
        "line_end": 1,
    }
    fields.update(overrides)
    return Observation.create(**fields)  # type: ignore[arg-type]


class TestUnknownIsExplicit(unittest.TestCase):
    """The rule this PR exists to enforce."""

    def test_unverifiable_provenance_defaults_to_unknown_not_to_a_guess(self):
        observation = _observation()

        # A local snapshot knows nothing about a remote repo or ref. It must
        # say so rather than inventing "main" because that is usually right.
        self.assertEqual(observation.repo, UNKNOWN)
        self.assertEqual(observation.ref, UNKNOWN)
        self.assertEqual(observation.commit, UNKNOWN)
        self.assertEqual(observation.worktree_state, UNKNOWN)
        self.assertEqual(observation.confidentiality, UNKNOWN)

    def test_an_empty_string_cannot_pass_as_a_known_value(self):
        """"" is the shape a fabricated-but-absent value takes. Reject it."""
        for field in ("repo", "ref", "commit", "snapshot_id"):
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    _observation(**{field: ""})

    def test_whitespace_cannot_pass_either(self):
        with self.assertRaises(ValueError):
            _observation(commit="   ")

    def test_unknown_is_not_a_usable_content_identity(self):
        """A source with no content hash cannot later be verified against."""
        observation = _observation(content_sha256=UNKNOWN)

        self.assertFalse(observation.is_verifiable())
        self.assertTrue(_observation().is_verifiable())

    def test_a_malformed_digest_is_rejected_rather_than_stored(self):
        for bad in ("abc", "z" * 64, "A" * 64):
            with self.subTest(digest=bad):
                with self.assertRaises(ValueError):
                    _observation(content_sha256=bad)

    def test_unknown_is_accepted_where_a_digest_would_go(self):
        self.assertEqual(_observation(content_sha256=UNKNOWN).content_sha256, UNKNOWN)


class TestProvenanceSemantics(unittest.TestCase):
    def test_source_type_is_closed(self):
        for good in ("local_file", "github_file", "ci", "memory"):
            with self.subTest(source_type=good):
                self.assertEqual(_observation(source_type=good).source_type, good)

        with self.assertRaises(ValueError):
            _observation(source_type="guess")

    def test_confidentiality_is_closed(self):
        for good in ("public", "internal", "secret", UNKNOWN):
            with self.subTest(confidentiality=good):
                self.assertEqual(
                    _observation(confidentiality=good).confidentiality, good
                )

        with self.assertRaises(ValueError):
            _observation(confidentiality="probably fine")

    def test_worktree_state_is_closed(self):
        for good in ("clean", "dirty", UNKNOWN):
            with self.subTest(worktree_state=good):
                self.assertEqual(_observation(worktree_state=good).worktree_state, good)

        with self.assertRaises(ValueError):
            _observation(worktree_state="probably clean")

    def test_a_dirty_worktree_means_the_commit_does_not_identify_the_bytes(self):
        """Design decision: snapshot identity is separate from commit identity.

        A commit SHA describes what is committed. A dirty worktree can serve
        different bytes from the same path, so the commit alone must not be
        treated as the identity of what was read.
        """
        clean = _observation(commit="c" * 40, worktree_state="clean")
        dirty = _observation(commit="c" * 40, worktree_state="dirty")

        self.assertTrue(clean.commit_identifies_content())
        self.assertFalse(dirty.commit_identifies_content())
        self.assertFalse(_observation(commit="c" * 40).commit_identifies_content())

    def test_content_hash_stays_authoritative_regardless_of_commit(self):
        """Content identity never depends on provenance being known."""
        self.assertTrue(_observation(commit=UNKNOWN).is_verifiable())


class TestLineRange(unittest.TestCase):
    def test_an_excerpt_must_declare_which_lines_it_covers(self):
        with self.assertRaises(ValueError):
            _observation(excerpt="# Demo repo", line_start=0, line_end=0)

    def test_an_empty_excerpt_declares_no_lines(self):
        observation = _observation(excerpt="", line_start=0, line_end=0)
        self.assertEqual((observation.line_start, observation.line_end), (0, 0))

        with self.assertRaises(ValueError):
            _observation(excerpt="", line_start=1, line_end=1)

    def test_the_range_must_run_forwards(self):
        with self.assertRaises(ValueError):
            _observation(excerpt="a\nb", line_start=5, line_end=2)

    def test_negative_lines_are_rejected(self):
        with self.assertRaises(ValueError):
            _observation(excerpt="a", line_start=-1, line_end=1)


class TestSourceId(unittest.TestCase):
    def test_source_id_is_derived_and_reproducible(self):
        first = _observation()
        second = _observation()

        self.assertEqual(first.source_id, second.source_id)
        self.assertEqual(
            first.source_id, derive_source_id("snap-1", "local_file", "README.md")
        )

    def test_source_id_identifies_the_source_not_the_content_version(self):
        """Re-reading a changed file is the same source with new content."""
        before = _observation(content_sha256="a" * 64)
        after = _observation(content_sha256="b" * 64)

        self.assertEqual(before.source_id, after.source_id)
        self.assertNotEqual(before.content_sha256, after.content_sha256)

    def test_different_sources_get_different_ids(self):
        self.assertNotEqual(
            _observation(path="README.md").source_id,
            _observation(path="docs/architecture.md").source_id,
        )
        self.assertNotEqual(
            _observation(snapshot_id="snap-1").source_id,
            _observation(snapshot_id="snap-2").source_id,
        )


class TestImmutability(unittest.TestCase):
    def test_an_observation_cannot_be_edited_after_collection(self):
        """Evidence that can be rewritten after the fact is not evidence."""
        observation = _observation()

        with self.assertRaises(FrozenInstanceError):
            observation.content_sha256 = "b" * 64  # type: ignore[misc]

    def test_replace_cannot_smuggle_past_validation(self):
        """`dataclasses.replace` calls __init__, not create().

        Validation therefore lives in __post_init__, or this would be a way to
        write a malformed digest into an object that already looked validated.
        """
        observation = _observation()

        with self.assertRaises(ValueError):
            replace(observation, content_sha256="INTE EN DIGEST")
        with self.assertRaises(ValueError):
            replace(observation, commit="")

    def test_an_observation_cannot_be_re_pointed_at_another_source(self):
        """source_id must keep naming the source it was derived from."""
        observation = _observation()

        with self.assertRaises(ValueError):
            replace(observation, path="docs/architecture.md")
        with self.assertRaises(ValueError):
            replace(observation, snapshot_id="snap-2")

    def test_replacing_content_is_allowed_because_the_source_is_unchanged(self):
        """Re-reading the same path is the same source with new content."""
        updated = replace(_observation(), content_sha256="b" * 64)

        self.assertEqual(updated.source_id, _observation().source_id)
        self.assertEqual(updated.content_sha256, "b" * 64)


class TestSchema(unittest.TestCase):
    def setUp(self):
        self.schema = json.loads(
            (ROOT / "schemas" / "atlas-observation.v1.json").read_text(encoding="utf-8")
        )

    def test_every_field_is_declared(self):
        declared = set(self.schema["properties"])
        actual = set(_observation().to_dict())

        self.assertEqual(actual, declared)

    def test_the_document_is_closed(self):
        self.assertIs(self.schema["additionalProperties"], False)

    def test_provenance_fields_allow_unknown(self):
        for field in ("repo", "ref", "commit", "snapshot_id", "content_sha256"):
            with self.subTest(field=field):
                spec = self.schema["properties"][field]
                self.assertIn(UNKNOWN, json.dumps(spec), f"{field} must permit unknown")

    def test_emitted_document_matches_the_schema(self):
        document = _observation().to_dict()

        self.assertEqual(document["schema"], "atlas-observation.v1")
        for key in self.schema["required"]:
            self.assertIn(key, document)

    def test_the_document_is_json_serialisable(self):
        json.loads(json.dumps(_observation().to_dict(), ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
