from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
import unittest

from atlas_core import AtlasController
from atlas_core.adapters.filesystem_repo import FilesystemRepoObserver
from atlas_core.budget import RunLimits
from atlas_core.evidence_base import EvidenceBase
from atlas_core.snapshot import take_snapshot


TASK = (
    "Granska CI-konfigurationen i atlas-core och avgör om Run Atlas Core "
    "använder samma testkommando som den ordinarie test-gaten. Ange exakt "
    "vilka workflow-filer som stöder svaret. Om underlaget inte räcker, säg "
    "det i stället för att gissa."
)
TEST_COMMAND = "uv run --locked --group ci python -m unittest discover -s tests"
LIMITS = RunLimits(
    wall_seconds=30,
    model_calls=0,
    tool_calls=16,
    tokens=0,
    output_bytes=400_000,
)


class TestDeterministicCiParityReview(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = self.tmp / "repo"
        workflows = self.root / ".github" / "workflows"
        workflows.mkdir(parents=True)
        self.workflows = workflows

    def _write_workflows(self, manual_commands: list[str]) -> None:
        (self.workflows / "test.yml").write_text(
            "name: test\n"
            "jobs:\n"
            "  python:\n"
            "    steps:\n"
            f"      - run: {TEST_COMMAND}\n",
            encoding="utf-8",
        )
        manual_lines = [
            "name: Run Atlas Core",
            "jobs:",
            "  atlas:",
            "    steps:",
            "      - name: Run tests",
        ]
        for command in manual_commands:
            manual_lines.append(f"        run: {command}")
        (self.workflows / "run-atlas.yml").write_text(
            "\n".join(manual_lines) + "\n",
            encoding="utf-8",
        )

    def _run(self) -> dict:
        snapshot = take_snapshot(self.root)
        return AtlasController(max_iterations=2).run(
            TASK,
            evidence=EvidenceBase(snapshot),
            observer=FilesystemRepoObserver(self.root),
            read_first=True,
            limits=LIMITS,
            json_mode=True,
        )

    def test_matching_test_commands_become_verified_findings(self) -> None:
        self._write_workflows([TEST_COMMAND])

        run = self._run()

        self.assertEqual(run["route"]["name"], "repo_review")
        self.assertEqual(run["plan"]["review"]["topic"], "ci")
        self.assertEqual(run["stop_reason"], "passed")
        self.assertEqual(run["iteration"], 1)
        self.assertIn(
            "använder samma normaliserade testkommandon",
            run["outputs"][-1],
        )

        checks = run["evaluations"][-1]["citation_checks"]
        self.assertEqual(len(checks), 2)
        self.assertEqual(
            {check["verdict"] for check in checks},
            {"verified"},
        )
        self.assertEqual(
            {
                check["claim_check"]["checked"]["path"]
                for check in checks
            },
            {
                ".github/workflows/test.yml",
                ".github/workflows/run-atlas.yml",
            },
        )

    def test_ambiguous_test_command_fails_closed(self) -> None:
        self._write_workflows(
            [
                TEST_COMMAND,
                "uv run --locked --group ci pytest -q",
            ]
        )

        run = self._run()

        self.assertEqual(run["route"]["name"], "repo_review")
        self.assertNotEqual(run["stop_reason"], "passed")
        self.assertIn(
            "findings_are_on_topic",
            run["evaluations"][-1]["unmet_criteria"],
        )
        self.assertEqual(run["evaluations"][-1]["citation_checks"], [])
        self.assertNotIn("CI test-command parity", run["outputs"][-1])


if __name__ == "__main__":
    unittest.main()
