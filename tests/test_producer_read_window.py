"""A deterministic producer's sources are read whole, up to a declared limit.

ROADMAP v2.2. The producers decline on a partial read, so the 80-line default
left them without a verdict on any longer file. These run the loop through the
filesystem observer, so the window is the observer's and not a test's.
"""

from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
import unittest
from typing import Any

from atlas_core import AtlasController
from atlas_core.adapters.filesystem_repo import FilesystemRepoObserver
from atlas_core.budget import RunLimits
from atlas_core.evidence_base import EvidenceBase
from atlas_core.review_plan import (
    PRODUCER_SOURCE_MAX_LINES,
    PRODUCER_SOURCE_PATHS,
)
from atlas_core.snapshot import DEFAULT_MAX_LINES, take_snapshot

CI_TASK = (
    "Granska CI-konfigurationen och avgör om Run Atlas Core använder samma "
    "testkommando som den ordinarie test-gaten."
)
GATE_PARITY_TASK = (
    "Kontrollera om release-check.sh och GitHub Actions har samma release-gates. "
    "Identifiera konkret drift mellan release-check.sh, tests.yml, "
    "markdownlint.yml och mq-stack-gate.yml."
)
TEST_COMMAND = "uv run --locked --group ci python -m unittest discover -s tests"
LIMITS = RunLimits(
    wall_seconds=30,
    model_calls=0,
    tool_calls=16,
    tokens=0,
    output_bytes=800_000,
)
TEST_GATE = ".github/workflows/test.yml"
POLICY = "scripts/check-gate-parity.py"

POLICY_TABLES = (
    "WORKFLOW_SCOPE: dict[str, str | bool] = {\n"
    '    "tests.yml": True,\n'
    '    "markdownlint.yml": True,\n'
    '    "mq-stack-gate.yml": False,\n'
    "}\n"
    "\n"
    "EXCEPTIONS: dict[str, str] = {\n"
    '    "markdownlint-cli2-action": "CI only action.",\n'
    "}\n"
)


def _padded(text: str, total_lines: int) -> str:
    """`text` followed by comment lines up to `total_lines` lines."""
    have = len(text.splitlines())
    return text + "".join(f"# line {n}\n" for n in range(have + 1, total_lines + 1))


class _WindowCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = self.tmp / "repo"
        self.root.mkdir()

    def _write(self, relative: str, text: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def _run(self, task: str, *, iterations: int = 2) -> dict[str, Any]:
        snapshot = take_snapshot(self.root)
        return AtlasController(max_iterations=iterations).run(
            task,
            evidence=EvidenceBase(snapshot),
            observer=FilesystemRepoObserver(self.root),
            read_first=True,
            limits=LIMITS,
            json_mode=True,
        )

    @staticmethod
    def _manifest(run: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return {
            item["path"]: item for item in run["evidence_manifest"]["observations"]
        }


class TestDeclaredLimit(unittest.TestCase):
    def test_the_limit_is_wider_than_the_default_window(self) -> None:
        self.assertGreater(PRODUCER_SOURCE_MAX_LINES, DEFAULT_MAX_LINES)

    def test_the_sources_are_exact_paths(self) -> None:
        for path in PRODUCER_SOURCE_PATHS:
            with self.subTest(path=path):
                self.assertFalse(set(path) & set("*?[]"))


class TestCiTestCommandParityWindow(_WindowCase):
    def _write_workflows(self, gate_lines: int, *, tail: str = "") -> None:
        gate = _padded("name: test\njobs:\n  python:\n    steps:\n", gate_lines - 1)
        # The command is the last line, so only a whole read finds it.
        self._write(TEST_GATE, gate + (tail or f"      - run: {TEST_COMMAND}\n"))
        self._write(
            ".github/workflows/run-atlas.yml",
            "name: Run Atlas Core\njobs:\n  atlas:\n    steps:\n"
            f"      - name: Run tests\n        run: {TEST_COMMAND}\n",
        )

    def test_a_gate_longer_than_the_default_window_gets_a_verdict(self) -> None:
        # 136 lines: atlas-core's own test.yml when the limitation was recorded.
        self._write_workflows(136)

        run = self._run(CI_TASK)

        self.assertEqual(run["stop_reason"], "passed")
        self.assertIn("samma normaliserade testkommandon", run["outputs"][-1])
        observed = self._manifest(run)[TEST_GATE]
        self.assertEqual(observed["line_end"], 136)
        self.assertIs(observed["read_in_full"], True)

    def test_a_second_test_command_in_the_tail_is_seen(self) -> None:
        self._write_workflows(
            136,
            tail=f"      - run: {TEST_COMMAND}\n      - run: uv run pytest -q\n",
        )

        run = self._run(CI_TASK)

        self.assertNotEqual(run["stop_reason"], "passed")
        self.assertNotIn("CI test-command parity", "".join(run["outputs"]))

    def test_a_gate_over_the_limit_is_cut_at_the_limit_and_declined(self) -> None:
        self._write_workflows(PRODUCER_SOURCE_MAX_LINES + 1)

        # One iteration: a second one re-reads the tail as its own window.
        run = self._run(CI_TASK, iterations=1)

        self.assertNotEqual(run["stop_reason"], "passed")
        self.assertNotIn("CI test-command parity", "".join(run["outputs"]))
        observed = self._manifest(run)[TEST_GATE]
        self.assertEqual(observed["line_end"], PRODUCER_SOURCE_MAX_LINES)
        self.assertEqual(observed["total_lines"], PRODUCER_SOURCE_MAX_LINES + 1)
        self.assertIs(observed["read_in_full"], False)

    def test_a_source_no_producer_rests_on_keeps_the_default_window(self) -> None:
        self._write_workflows(136)
        self._write(".github/workflows/other.yml", _padded("name: other\n", 136))

        run = self._run(CI_TASK)

        observed = self._manifest(run)[".github/workflows/other.yml"]
        self.assertEqual(observed["line_end"], DEFAULT_MAX_LINES)


class TestGateParityPolicyWindow(_WindowCase):
    def _write_repo(self, policy: str) -> None:
        self._write(
            "release-check.sh",
            "#!/usr/bin/env bash\n"
            'run_check "pytest" uv run pytest tests/\n'
            'run_check "check-gate-parity.py" uv run python scripts/check-gate-parity.py\n',
        )
        self._write(
            ".github/workflows/tests.yml",
            "jobs:\n  test:\n    steps:\n"
            "      - run: uv run pytest tests/\n"
            "      - run: uv run python scripts/check-gate-parity.py\n"
            "  release:\n    steps:\n      - run: ./release-check.sh\n",
        )
        self._write(
            ".github/workflows/markdownlint.yml",
            "jobs:\n  lint:\n    steps:\n"
            "      - uses: DavidAnson/markdownlint-cli2-action@v20\n",
        )
        self._write(
            ".github/workflows/mq-stack-gate.yml",
            "jobs:\n  gate:\n    steps:\n      - run: mq-agent stack contract-check\n",
        )
        self._write(POLICY, policy)

    def test_a_policy_of_224_lines_is_read_in_full(self) -> None:
        # 224 lines: the pinned mq-agent policy, over the earlier 200-line read.
        self._write_repo(_padded(POLICY_TABLES, 224))

        run = self._run(GATE_PARITY_TASK)

        self.assertEqual(run["stop_reason"], "passed")
        observed = self._manifest(run)[POLICY]
        self.assertEqual(observed["line_end"], 224)
        self.assertIs(observed["read_in_full"], True)

    def test_a_table_changed_after_line_200_declines(self) -> None:
        for change in (
            'WORKFLOW_SCOPE = {"tests.yml": False}',
            'WORKFLOW_SCOPE["mq-stack-gate.yml"] = True',
            'EXCEPTIONS["pytest"] = "not compared"',
        ):
            with self.subTest(change=change):
                self._write_repo(_padded(POLICY_TABLES, 223) + change + "\n")

                run = self._run(GATE_PARITY_TASK)

                self.assertNotEqual(run["stop_reason"], "passed")
                self.assertNotIn("CI/release gate parity", "".join(run["outputs"]))

    def test_a_policy_over_the_limit_declines(self) -> None:
        self._write_repo(_padded(POLICY_TABLES, PRODUCER_SOURCE_MAX_LINES + 1))

        run = self._run(GATE_PARITY_TASK)

        self.assertNotEqual(run["stop_reason"], "passed")
        self.assertNotIn("CI/release gate parity", "".join(run["outputs"]))
        self.assertIs(self._manifest(run)[POLICY]["read_in_full"], False)


if __name__ == "__main__":
    unittest.main()
