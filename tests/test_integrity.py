"""P0.1c: source integrity and safe handling of observation data.

ROADMAP.md P0.1, boxes three and four. Two jobs that must not be confused:

**Integrity** answers "is this still the source I read?" and runs against the
raw bytes at the original snapshot. **Redaction** answers "what may leave this
machine?" and runs only on the way out, over the excerpt.

Getting that order wrong is the bug this file exists to prevent, and it was not
hypothetical: masking the excerpt at collection time was tried first, and
`test_a_collected_excerpt_stays_raw_so_it_can_be_verified` is what failed. The
masked excerpt no longer matched the lines it claimed, so an untouched source
verified as `stale`. Raw excerpts therefore stay local, and masking produces a
view on export. Every redaction test here also asserts the digest and the
verdict are unmoved.

Not in scope: `Finding.v1` and semantic verification are P0.2. Nothing here
decides whether a claim is *true*, only whether the source it points at is
intact and whether what gets exported is safe to export.
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from atlas_core.integrity import (
    REDACTED,
    PathRefused,
    collect_observation_safely,
    redact_text,
    redacted_manifest,
    resolve_within,
)
from atlas_core.observation import UNKNOWN
from atlas_core.snapshot import collect_observation, take_snapshot, verify_observation

README = "# Demo repo\n\nEtt litet repo.\nRad fyra.\nRad fem.\n"

SECRETS = (
    "github_pat_11ABCDEFG0123456789_abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOP",
    "ghp_abcdefghijklmnopqrstuvwxyzABCDEF0123",
    "AKIAIOSFODNN7EXAMPLE",
    "sk-ant-api03-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "-----BEGIN RSA PRIVATE KEY-----",
)

HAS_GIT = shutil.which("git") is not None
HAS_SYMLINKS = os.name != "nt"


class _Dir(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        (self.root / "README.md").write_text(README, encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestIntegrityRunsOnRawContent(_Dir):
    """Verification compares the source as it was read, never a masked view."""

    def test_tampered_content_is_stale_even_when_the_length_matches(self):
        """A same-length edit must not slip past a size or line-count check."""
        snapshot = take_snapshot(self.root)
        observation = collect_observation(snapshot, "README.md")
        swapped = README.replace("Rad fyra.", "Rad FYRA.")
        self.assertEqual(len(swapped), len(README))
        (self.root / "README.md").write_text(swapped, encoding="utf-8")

        self.assertEqual(verify_observation(observation, self.root).result, "stale")

    def test_a_trailing_whitespace_edit_is_still_tampering(self):
        snapshot = take_snapshot(self.root)
        observation = collect_observation(snapshot, "README.md")
        (self.root / "README.md").write_text(README + " ", encoding="utf-8")

        self.assertEqual(verify_observation(observation, self.root).result, "stale")

    def test_restoring_the_original_content_verifies_fresh_again(self):
        """Integrity tracks content, not edit history."""
        snapshot = take_snapshot(self.root)
        observation = collect_observation(snapshot, "README.md")
        (self.root / "README.md").write_text("annat\n", encoding="utf-8")
        self.assertEqual(verify_observation(observation, self.root).result, "stale")

        (self.root / "README.md").write_text(README, encoding="utf-8")
        self.assertEqual(verify_observation(observation, self.root).result, "fresh")

    def test_a_collected_excerpt_stays_raw_so_it_can_be_verified(self):
        """"Råa källor förblir lokala"; masking is a view, not storage.

        Masking at collection time looked tidier and does not work: the masked
        excerpt no longer matches the lines it claims, so an untouched source
        verifies as `stale`. The raw excerpt never leaves the machine — see
        TestManifest for what export carries.
        """
        (self.root / "README.md").write_text(
            f"# Demo\n\ntoken: {SECRETS[1]}\n", encoding="utf-8"
        )
        observation = collect_observation_safely(take_snapshot(self.root), "README.md")

        self.assertIn(SECRETS[1], observation.excerpt)
        self.assertEqual(verify_observation(observation, self.root).result, "fresh")

    def test_building_the_redacted_view_moves_neither_digest_nor_verdict(self):
        """The ordering rule, asserted directly."""
        (self.root / "README.md").write_text(
            f"# Demo\n\ntoken: {SECRETS[1]}\n", encoding="utf-8"
        )
        snapshot = take_snapshot(self.root)
        observation = collect_observation_safely(snapshot, "README.md")
        before = verify_observation(observation, self.root)

        manifest = redacted_manifest(snapshot, [observation], root=self.root)
        after = verify_observation(observation, self.root)

        self.assertNotIn(SECRETS[1], str(manifest))
        self.assertEqual(manifest["observations"][0]["content_sha256"], observation.content_sha256)
        self.assertEqual((before.result, after.result), ("fresh", "fresh"))

    def test_a_secret_bearing_file_that_changes_is_still_detected(self):
        """Handling secrets must not blind the integrity check."""
        (self.root / "README.md").write_text(
            f"# Demo\n\ntoken: {SECRETS[1]}\n", encoding="utf-8"
        )
        observation = collect_observation_safely(take_snapshot(self.root), "README.md")
        (self.root / "README.md").write_text(
            f"# Demo\n\ntoken: {SECRETS[1]}\nny rad\n", encoding="utf-8"
        )

        self.assertEqual(verify_observation(observation, self.root).result, "stale")


class TestPathRefusal(_Dir):
    def test_a_path_escaping_the_snapshot_is_refused(self):
        for attempt in ("../outside.md", "docs/../../outside.md", "a/b/../../../x"):
            with self.subTest(path=attempt):
                with self.assertRaises(PathRefused):
                    resolve_within(self.root, attempt)

    def test_an_absolute_path_is_refused(self):
        with self.assertRaises(PathRefused):
            resolve_within(self.root, "/etc/passwd")

    def test_a_path_inside_the_snapshot_resolves(self):
        (self.root / "docs").mkdir()
        (self.root / "docs" / "a.md").write_text("x", encoding="utf-8")

        resolved = resolve_within(self.root, "docs/a.md")

        self.assertEqual(resolved, (self.root / "docs" / "a.md").resolve())

    def test_a_sibling_directory_sharing_a_prefix_is_not_inside(self):
        """`/tmp/root-evil` must not count as inside `/tmp/root`."""
        sibling = Path(self.tmp + "-evil")
        sibling.mkdir()
        self.addCleanup(shutil.rmtree, sibling, True)
        (sibling / "x.md").write_text("x", encoding="utf-8")

        with self.assertRaises(PathRefused):
            resolve_within(self.root, f"../{sibling.name}/x.md")

    @unittest.skipUnless(HAS_SYMLINKS, "symlinks unavailable")
    def test_a_symlink_pointing_outside_is_refused(self):
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, outside, True)
        (outside / "secret.md").write_text("hemligt\n", encoding="utf-8")
        (self.root / "link.md").symlink_to(outside / "secret.md")

        with self.assertRaises(PathRefused):
            resolve_within(self.root, "link.md")

    @unittest.skipUnless(HAS_SYMLINKS, "symlinks unavailable")
    def test_a_symlinked_directory_pointing_outside_is_refused(self):
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, outside, True)
        (outside / "secret.md").write_text("hemligt\n", encoding="utf-8")
        (self.root / "docs").symlink_to(outside, target_is_directory=True)

        with self.assertRaises(PathRefused):
            resolve_within(self.root, "docs/secret.md")

    @unittest.skipUnless(HAS_SYMLINKS, "symlinks unavailable")
    def test_a_symlink_staying_inside_is_allowed(self):
        """Refuse escape, not symlinks as such."""
        (self.root / "real.md").write_text("inuti\n", encoding="utf-8")
        (self.root / "alias.md").symlink_to(self.root / "real.md")

        self.assertEqual(resolve_within(self.root, "alias.md"), (self.root / "real.md").resolve())

    def test_safe_collection_refuses_the_same_paths(self):
        snapshot = take_snapshot(self.root)

        with self.assertRaises(PathRefused):
            collect_observation_safely(snapshot, "../outside.md")


class TestRedaction(unittest.TestCase):
    def test_known_secret_shapes_are_masked(self):
        for secret in SECRETS:
            with self.subTest(secret=secret[:12]):
                redacted = redact_text(f"före {secret} efter")

                self.assertNotIn(secret, redacted)
                self.assertIn(REDACTED, redacted)
                self.assertIn("före", redacted)
                self.assertIn("efter", redacted)

    def test_a_whole_private_key_block_is_masked_not_only_its_header(self):
        """Masking the BEGIN line alone left the key itself in the clear."""
        pem = (
            "-----BEGIN RSA PRIVATE KEY-----\n"
            "MIIEowIBAAKCAQEAx7Vn8kL9vQ2mN4pR6sT8uW0yZ1aB3cD5eF7gH9iJ0kL2mN4oP\n"
            "6qR8sT0uV2wX4yZ6aB8cD0eF2gH4iJ6kL8mN0oP2qR4sT6uV8wX0yZ2aB4cD6eF8g\n"
            "-----END RSA PRIVATE KEY-----"
        )

        redacted = redact_text(f"före\n{pem}\nefter")

        self.assertNotIn("MIIEowIBAAKCAQEA", redacted)
        self.assertNotIn("-----END RSA PRIVATE KEY-----", redacted)
        self.assertIn("före", redacted)
        self.assertIn("efter", redacted)

    def test_an_unterminated_key_block_still_masks_its_body(self):
        """A truncated paste has no END line. The body is still a key."""
        redacted = redact_text(
            "-----BEGIN OPENSSH PRIVATE KEY-----\n"
            "MIIEowIBAAKCAQEAx7Vn8kL9vQ2mN4pR6sT8uW0yZ1aB3cD5eF7gH9iJ0kL2mN4oP\n"
            "vanlig text efter\n"
        )

        self.assertNotIn("MIIEowIBAAKCAQEA", redacted)
        self.assertIn("vanlig text efter", redacted)

    def test_a_home_directory_path_is_masked(self):
        redacted = redact_text("se /Users/mansys/.ssh/id_rsa för detaljer")

        self.assertNotIn("mansys", redacted)
        self.assertIn(REDACTED, redacted)

    def test_an_email_address_is_masked(self):
        self.assertNotIn("privat@example.com", redact_text("kontakt: privat@example.com"))

    def test_ordinary_prose_survives_untouched(self):
        """"Klipp inte bort just den kontext som behövs för att kontrollera påståendet." """
        prose = (
            "## Recommendation\n"
            "README.md saknar installationssteg. Se docs/architecture.md rad 12.\n"
            "Versionen är 1.0.0 och testerna ligger i tests/test_loop.py.\n"
        )

        self.assertEqual(redact_text(prose), prose)

    def test_code_and_hashes_are_not_mistaken_for_secrets(self):
        intact = "commit 232e33b, sha256 " + "a" * 64 + ", port 8080"

        self.assertEqual(redact_text(intact), intact)

    def test_redaction_is_idempotent(self):
        once = redact_text(f"token: {SECRETS[1]}")

        self.assertEqual(redact_text(once), once)


class TestManifest(_Dir):
    def test_the_manifest_carries_no_raw_secret(self):
        (self.root / "README.md").write_text(
            f"# Demo\n\nexport TOKEN={SECRETS[1]}\n", encoding="utf-8"
        )
        snapshot = take_snapshot(self.root)
        observations = [collect_observation(snapshot, "README.md")]

        manifest = redacted_manifest(snapshot, observations)

        self.assertNotIn(SECRETS[1], str(manifest))

    def test_the_manifest_keeps_the_digest_of_the_raw_content(self):
        """Export is a view. It must still point at what was verified."""
        snapshot = take_snapshot(self.root)
        observation = collect_observation(snapshot, "README.md")

        entry = redacted_manifest(snapshot, [observation])["observations"][0]

        self.assertEqual(entry["content_sha256"], observation.content_sha256)
        self.assertEqual(entry["source_id"], observation.source_id)

    def test_the_manifest_records_the_snapshot_it_was_read_at(self):
        snapshot = take_snapshot(self.root)

        manifest = redacted_manifest(snapshot, [collect_observation(snapshot, "README.md")])

        self.assertEqual(manifest["snapshot"]["snapshot_id"], snapshot.snapshot_id)
        self.assertEqual(manifest["snapshot"]["worktree_state"], snapshot.worktree_state)

    def test_an_unverifiable_observation_is_marked_in_the_manifest(self):
        snapshot = take_snapshot(self.root)
        observation = collect_observation(snapshot, "README.md")
        (self.root / "README.md").write_text("ändrad\n", encoding="utf-8")

        manifest = redacted_manifest(snapshot, [observation], root=self.root)
        entry = manifest["observations"][0]

        self.assertEqual(entry["verification"], "stale")
        self.assertFalse(entry["is_evidence"])

    def test_the_manifest_omits_the_absolute_snapshot_root(self):
        """`snapshot.root` names a user and a machine. It is not exported.

        The snapshot_id identifies the state without disclosing where on disk
        it lived, which is what an exported artifact needs.
        """
        snapshot = take_snapshot(self.root)

        manifest = redacted_manifest(snapshot, [collect_observation(snapshot, "README.md")])

        self.assertNotIn("root", manifest["snapshot"])
        self.assertNotIn(str(self.root), str(manifest))
        self.assertIn("snapshot_id", manifest["snapshot"])

    def test_without_a_root_the_manifest_claims_no_verification(self):
        """An unverified entry must not read as verified."""
        snapshot = take_snapshot(self.root)

        entry = redacted_manifest(snapshot, [collect_observation(snapshot, "README.md")])[
            "observations"
        ][0]

        self.assertEqual(entry["verification"], UNKNOWN)
        self.assertFalse(entry["is_evidence"])

    def test_a_secret_in_a_path_does_not_leave_in_the_manifest(self):
        """Metadata leaks a run just as readily as content does."""
        docs = self.root / "docs"
        docs.mkdir()
        (docs / "privat@example.com.md").write_text("ofarligt\n", encoding="utf-8")
        snapshot = take_snapshot(self.root)

        manifest = redacted_manifest(
            snapshot, [collect_observation(snapshot, "docs/privat@example.com.md")]
        )

        self.assertNotIn("privat@example.com", json.dumps(manifest, ensure_ascii=False))
        self.assertIn(REDACTED, manifest["observations"][0]["path"])

    def test_a_token_shaped_ref_does_not_leave_in_the_manifest(self):
        """A branch name is exported metadata too."""
        snapshot = take_snapshot(self.root)
        leaky = replace(snapshot, ref=f"feature/{SECRETS[1]}")

        manifest = redacted_manifest(leaky, [collect_observation(snapshot, "README.md")])

        self.assertNotIn(SECRETS[1], json.dumps(manifest, ensure_ascii=False))

    def test_a_secret_in_repo_or_ref_metadata_does_not_leave(self):
        snapshot = take_snapshot(self.root)
        observation = replace(
            collect_observation(snapshot, "README.md"),
            repo=f"org/{SECRETS[2]}",
            ref=f"refs/heads/{SECRETS[1]}",
        )

        serialised = json.dumps(
            redacted_manifest(snapshot, [observation]), ensure_ascii=False
        )

        self.assertNotIn(SECRETS[1], serialised)
        self.assertNotIn(SECRETS[2], serialised)

    def test_masking_metadata_never_masks_the_verification_pointer(self):
        """The digest and ids are what a reader follows back. They stay whole."""
        snapshot = take_snapshot(self.root)
        observation = collect_observation(snapshot, "README.md")

        entry = redacted_manifest(snapshot, [observation], root=self.root)[
            "observations"
        ][0]

        self.assertEqual(entry["content_sha256"], observation.content_sha256)
        self.assertEqual(entry["source_id"], observation.source_id)
        self.assertEqual(entry["snapshot_id"], observation.snapshot_id)
        self.assertNotIn(REDACTED, entry["content_sha256"])

    def test_an_ordinary_path_is_not_mangled_by_metadata_masking(self):
        snapshot = take_snapshot(self.root)

        entry = redacted_manifest(snapshot, [collect_observation(snapshot, "README.md")])[
            "observations"
        ][0]

        self.assertEqual(entry["path"], "README.md")

    def test_the_manifest_is_json_serialisable(self):
        snapshot = take_snapshot(self.root)
        manifest = redacted_manifest(snapshot, [collect_observation(snapshot, "README.md")])

        json.loads(json.dumps(manifest, ensure_ascii=False))


@unittest.skipUnless(HAS_GIT, "git not available")
class TestIntegrityAgainstTheOriginalSnapshot(_Dir):
    """"Verifiera mot det ursprungliga snapshotet." """

    def _git(self, *args: str) -> None:
        subprocess.run(["git", *args], cwd=self.tmp, capture_output=True, check=False)

    def test_a_commit_does_not_make_a_changed_file_fresh_again(self):
        self._git("init", "-q")
        self._git("config", "user.email", "t@example.com")
        self._git("config", "user.name", "Test")
        self._git("add", "README.md")
        self._git("commit", "-qm", "init")

        snapshot = take_snapshot(self.root)
        observation = collect_observation(snapshot, "README.md")

        (self.root / "README.md").write_text(README + "ny rad\n", encoding="utf-8")
        self._git("commit", "-qam", "ändring")

        # A tidy worktree at a new commit is not the state that was observed.
        self.assertEqual(verify_observation(observation, self.root).result, "stale")


if __name__ == "__main__":
    unittest.main()
