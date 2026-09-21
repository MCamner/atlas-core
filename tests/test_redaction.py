"""P0.1, box four: what may leave the machine, and what a source is marked as.

Two things are checked here, and they are the two the roadmap left open:

- `confidentiality` is derived from what the content actually carries, instead
  of staying `unknown` because nobody said otherwise.
- Redaction covers the **whole** exported run document, not only the manifest.
  The prose observation channel and the produced output used to leave verbatim,
  which meant a secret an adapter had formatted into context was exported in
  full while the manifest beside it was masked.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from atlas_core.controller import AtlasController
from atlas_core.finalizer import render_run_text
from atlas_core.integrity import collect_observation_safely, redacted_manifest
from atlas_core.redaction import (
    REDACTED,
    classify_confidentiality,
    redact_document,
    redact_text,
)
from atlas_core.snapshot import collect_observation, take_snapshot

SECRET = "ghp_" + "a" * 36
HOME = "/Users/someone/.ssh/id_rsa"


class TestClassification(unittest.TestCase):
    """A class is assigned from evidence in the content, or left unknown."""

    def test_a_credential_shape_makes_the_content_secret(self):
        self.assertEqual(classify_confidentiality(f"token = {SECRET}\n"), "secret")

    def test_personal_data_makes_the_content_internal(self):
        self.assertEqual(classify_confidentiality("kontakt: a@example.com\n"), "internal")
        self.assertEqual(classify_confidentiality(f"cache in {HOME}\n"), "internal")

    def test_a_credential_outranks_personal_data(self):
        self.assertEqual(
            classify_confidentiality(f"a@example.com {SECRET}"), "secret"
        )

    def test_content_with_no_marker_is_unknown_and_never_public(self):
        """Absence of a detected marker is not proof that a source is public.

        Returning `public` here is the one answer this function may not give:
        the detection is narrow by design, so "nothing matched" means the
        classifier found nothing, not that there is nothing to find.
        """
        self.assertEqual(classify_confidentiality("# Atlas Core\n\npip install\n"), "unknown")


class TestCollectionClassifies(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        (self.root / "config.env").write_text(f"TOKEN={SECRET}\n", encoding="utf-8")
        (self.root / "README.md").write_text("# Atlas\n\npip install\n", encoding="utf-8")
        self.snapshot = take_snapshot(self.root)

    def test_a_collected_source_carries_the_class_its_content_earns(self):
        observation = collect_observation(self.snapshot, "config.env")

        self.assertEqual(observation.confidentiality, "secret")

    def test_a_source_with_no_marker_stays_unknown(self):
        observation = collect_observation(self.snapshot, "README.md")

        self.assertEqual(observation.confidentiality, "unknown")

    def test_the_safe_collector_classifies_too(self):
        observation = collect_observation_safely(self.snapshot, "config.env")

        self.assertEqual(observation.confidentiality, "secret")

    def test_a_caller_that_states_a_class_is_not_overruled(self):
        """A human who knows the source outranks a pattern match."""
        observation = collect_observation(
            self.snapshot, "config.env", confidentiality="internal"
        )

        self.assertEqual(observation.confidentiality, "internal")

    def test_classifying_moves_neither_the_digest_nor_the_excerpt(self):
        """Raw stays raw. The class is a label on the source, not an edit of it."""
        observation = collect_observation(self.snapshot, "config.env")

        self.assertIn(SECRET, observation.excerpt)
        self.assertEqual(
            observation.content_sha256,
            collect_observation(self.snapshot, "config.env").content_sha256,
        )


class TestRedactDocument(unittest.TestCase):
    def test_it_reaches_strings_nested_in_lists_and_objects(self):
        document = {
            "outputs": [f"found {SECRET} in {HOME}"],
            "nested": {"note": "mail a@example.com"},
        }

        redacted = redact_document(document)

        self.assertNotIn(SECRET, str(redacted))
        self.assertNotIn("a@example.com", str(redacted))
        self.assertNotIn("/Users/someone", str(redacted))

    def test_pointer_fields_survive_verbatim(self):
        """The ids are what a reader follows back; masking them points nowhere."""
        digest = "a" * 64
        document = {"content_sha256": digest, "source_id": "0123456789abcdef"}

        self.assertEqual(redact_document(document), document)

    def test_masking_twice_changes_nothing_further(self):
        once = redact_document({"note": f"{SECRET}"})

        self.assertEqual(redact_document(once), once)

    def test_non_strings_are_left_alone(self):
        document = {"iteration": 2, "passed": True, "score": 0.5, "nothing": None}

        self.assertEqual(redact_document(document), document)


class TestTheRunDocumentIsMasked(unittest.TestCase):
    """The hole this closes: prose context left the run verbatim.

    `redacted_manifest` masked the evidence channel from the start. The
    `observations` list an adapter formats is a *different* channel, and it was
    exported exactly as given — so a run whose manifest was clean could still
    publish the same secret one key away.
    """

    def test_a_secret_in_the_prose_channel_does_not_leave_the_run(self):
        run = AtlasController(max_iterations=1).run(
            "granska repot",
            observations=[f"config.env:\nTOKEN={SECRET}\n"],
            json_mode=True,
        )

        self.assertNotIn(SECRET, str(run))
        self.assertIn(REDACTED, str(run["observations"]))

    def test_the_produced_answer_is_masked_as_well(self):
        """The output repeats its sources, so masking one channel is not enough."""
        run = AtlasController(max_iterations=1).run(
            "granska repot",
            observations=[f"notes.md:\nhem: {HOME}\n"],
            json_mode=True,
        )

        self.assertNotIn("/Users/someone", str(run["outputs"]))

    def test_the_text_a_human_reads_is_masked_too(self):
        text = AtlasController(max_iterations=1).run(
            "granska repot", observations=[f"config.env:\nTOKEN={SECRET}\n"]
        )

        self.assertNotIn(SECRET, text)

    def test_the_task_itself_is_masked(self):
        run = AtlasController(max_iterations=1).run(
            f"granska {HOME}", json_mode=True
        )

        self.assertNotIn("/Users/someone", str(run))


class TestManifestStillMasks(unittest.TestCase):
    """The manifest path keeps working through the shared implementation."""

    def test_an_excerpt_leaves_the_manifest_masked(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, True)
        (root / "config.env").write_text(f"TOKEN={SECRET}\n", encoding="utf-8")
        snapshot = take_snapshot(root)
        observation = collect_observation(snapshot, "config.env")

        manifest = redacted_manifest(snapshot, [observation])

        self.assertNotIn(SECRET, str(manifest))
        self.assertEqual(manifest["observations"][0]["confidentiality"], "secret")

    def test_redact_text_is_unchanged_for_its_callers(self):
        self.assertEqual(redact_text(f"x {SECRET} y"), f"x {REDACTED} y")


@unittest.skipUnless(os.name != "nt", "symlinks unavailable")
class TestVerificationContainment(unittest.TestCase):
    """Re-reading is a read, and every read is contained. See box four."""

    def test_a_symlink_out_of_the_root_is_refused_when_re_verified(self):
        from atlas_core.snapshot import verify_observation

        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, True)
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, outside, True)
        (root / "notes.md").write_text("hemligt\n", encoding="utf-8")
        snapshot = take_snapshot(root)
        observation = collect_observation(snapshot, "notes.md")

        # The name was legal when it was read. It is a link out of the root by
        # the time anything re-reads it, which is exactly the case a check made
        # at collection time cannot cover.
        (root / "notes.md").unlink()
        (outside / "notes.md").write_text("hemligt\n", encoding="utf-8")
        (root / "notes.md").symlink_to(outside / "notes.md")

        verification = verify_observation(observation, root)

        self.assertEqual(verification.result, "refused")
        self.assertFalse(verification.is_evidence())


class TestVerificationDoesNotGuess(unittest.TestCase):
    def test_a_non_local_source_is_not_read_off_the_snapshot_root(self):
        """A `ci` identifier is not a file name, and must not be treated as one."""
        from atlas_core.ci import CIRun, StubCIAdapter, collect_ci_observation
        from atlas_core.snapshot import verify_observation

        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, True)
        snapshot = take_snapshot(root)
        run = CIRun(
            provider="github",
            workflow="test.yml",
            run_id="1",
            ref="main",
            commit="b" * 40,
            conclusion="success",
            completed_at="2026-09-21T00:00:00+00:00",
        )
        observation = collect_ci_observation(snapshot, StubCIAdapter(run), "main")

        verification = verify_observation(observation, root)

        self.assertEqual(verification.result, "unverifiable")
        self.assertFalse(verification.is_evidence())


if __name__ == "__main__":
    unittest.main()
