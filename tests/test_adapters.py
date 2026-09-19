import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from atlas_core.adapters.filesystem_repo import FilesystemRepoAdapter
from atlas_core.adapters.github_reader import GitHubRepoAdapter
from atlas_core.adapters.mqobsidian import MQObsidianMemoryAdapter
from atlas_core.cli import main
from atlas_core.controller import AtlasController


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


class TestMQObsidianMemoryAdapter(unittest.TestCase):
    def test_reads_small_context_surfaces_in_contract_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            context = vault / ".mq" / "context"
            agent = vault / "memory" / "learn" / "agent"
            system = vault / "systems" / "demo"
            cards = vault / "memory" / "context-cards"
            for directory in (context, agent, system, cards):
                directory.mkdir(parents=True, exist_ok=True)
            (context / "task-pack.md").write_text(
                "---\ntask: task\nrepo: demo\n---\n\ntask pack", encoding="utf-8"
            )
            (agent / "demo.md").write_text("agent view", encoding="utf-8")
            (system / "hot.md").write_text("hot state", encoding="utf-8")
            (system / "index.md").write_text("stable index", encoding="utf-8")
            (cards / "demo-card.md").write_text("context card", encoding="utf-8")

            observations = MQObsidianMemoryAdapter(vault, project="demo").read("task")

        self.assertEqual(len(observations), 5)
        self.assertIn("task-pack.md", observations[0])
        self.assertIn("memory/learn/agent/demo.md", observations[1])
        self.assertTrue(all("Durable memory" in item for item in observations))

    def test_skips_task_pack_for_another_task_or_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            context = vault / ".mq" / "context"
            context.mkdir(parents=True)
            (context / "task-pack.md").write_text(
                "---\ntask: another task\nrepo: other\n---\n\nstale", encoding="utf-8"
            )

            observations = MQObsidianMemoryAdapter(vault, project="demo").read("task")

        self.assertEqual(observations, [])

    def test_writes_only_atlas_memory_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter = MQObsidianMemoryAdapter(tmp, project="demo")
            path = adapter.write(
                {
                    "schema": "atlas-memory-candidate.v1",
                    "created_at": "2026-09-19T10:00:00+00:00",
                    "summary": "candidate",
                }
            )
            self.assertIsNotNone(path)
            self.assertIn("inbox/atlas-memory-candidates", path)
            self.assertTrue(Path(path).is_file())

            with self.assertRaises(ValueError):
                adapter.write({"schema": "runtime-truth.v1", "summary": "no"})

    def test_rejects_unsafe_project_name_and_sanitizes_candidate_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                MQObsidianMemoryAdapter(tmp, project="..")
            adapter = MQObsidianMemoryAdapter(tmp, project="demo")
            path = adapter.write(
                {
                    "schema": "atlas-memory-candidate.v1",
                    "created_at": "../../outside",
                }
            )
            self.assertEqual(Path(path).parent.name, "atlas-memory-candidates")
            self.assertNotIn("..", Path(path).name)

    def test_controller_reads_memory_and_writes_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            agent = vault / "memory" / "learn" / "agent"
            agent.mkdir(parents=True)
            (agent / "demo.md").write_text("prior decision", encoding="utf-8")
            adapter = MQObsidianMemoryAdapter(vault, project="demo")

            state = AtlasController(memory_adapter=adapter).run("hej", json_mode=True)

            self.assertIn("prior decision", state["observations"][0])
            self.assertIn("saved_path", state["memory_candidates"][0])

    def test_cli_requires_path_and_project_together(self):
        with patch("sys.stderr"):
            with self.assertRaises(SystemExit) as ctx:
                main(["run", "hej", "--mqobsidian-path", "/tmp/vault"])
        self.assertEqual(ctx.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
