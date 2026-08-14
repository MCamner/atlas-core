import tempfile
import unittest
from pathlib import Path

from atlas_core.adapters.filesystem_repo import FilesystemRepoAdapter
from atlas_core.adapters.github_reader import GitHubRepoAdapter


class TestFilesystemRepoAdapter(unittest.TestCase):
    def test_reads_readme(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("# Demo\n\nHello", encoding="utf-8")
            obs = FilesystemRepoAdapter(str(root)).observe("granska repo")
        self.assertTrue(any("README.md" in item for item in obs))


class TestGitHubRepoAdapter(unittest.TestCase):
    def test_requires_owner_name(self):
        with self.assertRaises(ValueError) as ctx:
            GitHubRepoAdapter("not-a-full-name")
        self.assertIn("owner/name", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
