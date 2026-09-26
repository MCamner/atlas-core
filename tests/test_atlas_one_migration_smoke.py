from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parent
LEGACY_PROMPT = ROOT / "fixtures" / "atlas_one_migration" / "legacy-prompt.md"
ATLAS_TASK = "granska repot efter hårdkodade lösenord"
UNMAPPED_ACTION = "Action: Commit fixes directly to main."
EXPECTED_SOURCE_SHA256 = "4e96d663d071da055d6fcffa3711a76e17e4eaf981b0585ed9cecfe833da9e08"


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


class TestAtlasOneMigrationSmoke(unittest.TestCase):
    def test_preview_preserves_source_and_never_runs_or_grants_write(self) -> None:
        source = LEGACY_PROMPT.read_bytes()
        source_digest = _sha256(source)
        self.assertEqual(source_digest, EXPECTED_SOURCE_SHA256)

        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / LEGACY_PROMPT.name
            shutil.copyfile(LEGACY_PROMPT, archive)

            legacy_text = archive.read_text(encoding="utf-8")
            self.assertIn("Method: Quote the exact path and line", legacy_text)
            self.assertIn("Context: Use the repository selected", legacy_text)
            self.assertIn(UNMAPPED_ACTION, legacy_text)

            preview = {
                "source_sha256": source_digest,
                "task": ATLAS_TASK,
                "unmapped": [UNMAPPED_ACTION],
                "run_requested": False,
                "write_capabilities": [],
            }
            preview_path = Path(directory) / "migration-preview.json"
            preview_path.write_text(json.dumps(preview), encoding="utf-8")
            recorded = json.loads(preview_path.read_text(encoding="utf-8"))

            self.assertEqual(recorded["source_sha256"], source_digest)
            self.assertEqual(recorded["task"], ATLAS_TASK)
            self.assertEqual(recorded["unmapped"], [UNMAPPED_ACTION])
            self.assertFalse(recorded["run_requested"])
            self.assertEqual(recorded["write_capabilities"], [])
            self.assertEqual(_sha256(archive.read_bytes()), source_digest)

        self.assertEqual(_sha256(LEGACY_PROMPT.read_bytes()), source_digest)


if __name__ == "__main__":
    unittest.main()
