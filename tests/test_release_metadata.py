import json
import tomllib
import unittest
from pathlib import Path

import atlas_core


ROOT = Path(__file__).parents[1]


class TestReleaseMetadata(unittest.TestCase):
    def test_version_is_synchronized(self):
        version_file = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        manifest = json.loads((ROOT / "MANIFEST.json").read_text(encoding="utf-8"))

        self.assertEqual(version_file, "1.0.0")
        self.assertEqual(pyproject["project"]["version"], version_file)
        self.assertEqual(manifest["version"], version_file)
        self.assertEqual(atlas_core.__version__, version_file)

    def test_changelog_has_v1_release_section(self):
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("## v1.0.0 — 2026-09-19", changelog)
        self.assertLess(changelog.index("## Unreleased"), changelog.index("## v1.0.0"))


if __name__ == "__main__":
    unittest.main()
