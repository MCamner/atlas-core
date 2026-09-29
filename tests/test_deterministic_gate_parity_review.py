from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
import unittest

from atlas_core import AtlasController
from atlas_core.adapters.filesystem_repo import FilesystemRepoObserver
from atlas_core.budget import RunLimits
from atlas_core.evidence_base import EvidenceBase
from atlas_core.finalizer import FACT, render_run_text
from atlas_core.snapshot import take_snapshot


TASK = (
    "Kontrollera om release-check.sh och GitHub Actions har samma release-gates. "
    "Identifiera konkret drift mellan release-check.sh, tests.yml, "
    "markdownlint.yml och mq-stack-gate.yml. Rapportera endast fynd som kan "
    "styrkas med de lästa filerna."
)
LIMITS = RunLimits(
    wall_seconds=30,
    model_calls=0,
    tool_calls=16,
    tokens=0,
    output_bytes=400_000,
)


class TestDeterministicGateParityReview(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = self.tmp / "repo"
        workflows = self.root / ".github" / "workflows"
        workflows.mkdir(parents=True)
        scripts = self.root / "scripts"
        scripts.mkdir()
        self.workflows = workflows
        self.scripts = scripts

        policy = """#!/usr/bin/env python3
\"\"\"Parity policy.

Differences are allowed only when declared in
EXCEPTIONS below with a reason. This prose must never start block parsing.
\"\"\"

WORKFLOW_SCOPE: dict[str, str | bool] = {
    "tests.yml": True,
    "markdownlint.yml": True,
    "mq-stack-gate.yml": False,
    "release.yml": False,
}

EXCEPTIONS: dict[str, str] = {
    "check-vendored-contracts.py": (
        "CI only: compares against a canonical checkout."
    ),
    "markdownlint-cli2-action": (
        "CI only action; local markdown style is not release blocking."
    ),
}
"""
        (scripts / "check-gate-parity.py").write_text(policy, encoding="utf-8")
        (workflows / "markdownlint.yml").write_text(
            "jobs:\n"
            "  lint:\n"
            "    steps:\n"
            "      - uses: actions/checkout@v4\n"
            "      - uses: DavidAnson/markdownlint-cli2-action@v20\n",
            encoding="utf-8",
        )
        (workflows / "mq-stack-gate.yml").write_text(
            "name: stack\njobs:\n  gate:\n    steps:\n      - run: mq-agent stack contract-check\n",
            encoding="utf-8",
        )

    def _write_release_gate(self) -> None:
        filler = "".join(f"# filler {index}\n" for index in range(90))
        (self.root / "release-check.sh").write_text(
            "#!/usr/bin/env bash\n"
            + filler
            + 'run_check "pytest" uv run pytest tests/\n'
            + 'run_check "ruff" uv run ruff check src/ tests/\n'
            + 'run_check "check-gate-parity.py" uv run python scripts/check-gate-parity.py\n',
            encoding="utf-8",
        )

    def _write_tests_workflow(self, *, ruff_targets: str = "src/ tests/") -> None:
        filler = "".join(f"      # filler {index}\n" for index in range(90))
        (self.workflows / "tests.yml").write_text(
            "name: Tests\n"
            "jobs:\n"
            "  test:\n"
            "    steps:\n"
            "      - uses: actions/checkout@v4\n"
            "      - run: uv run pytest tests/\n"
            "      - run: uv run python scripts/check-vendored-contracts.py --canonical-root .canonical-contracts\n"
            f"      - run: uv run ruff check {ruff_targets}\n"
            "      - run: uv run python scripts/check-gate-parity.py\n"
            + filler
            + "  macos-runtime:\n"
            "    steps:\n"
            "      - run: ./release-check.sh\n",
            encoding="utf-8",
        )

    def _run(self) -> dict:
        snapshot = take_snapshot(self.root)
        return AtlasController(max_iterations=3).run(
            TASK,
            evidence=EvidenceBase(snapshot),
            observer=FilesystemRepoObserver(self.root),
            read_first=True,
            limits=LIMITS,
            json_mode=True,
        )

    def test_matching_local_and_ci_gates_become_an_on_topic_result(self) -> None:
        self._write_release_gate()
        self._write_tests_workflow()

        run = self._run()

        self.assertEqual(run["route"]["name"], "repo_review")
        self.assertEqual(run["plan"]["review"]["topic"], "ci_gate_parity")
        self.assertEqual(run["stop_reason"], "passed")
        self.assertIn("ingen odeklarerad drift", run["outputs"][-1])
        self.assertNotIn("CI-only check: check-vendored-contracts.py", run["outputs"][-1])
        self.assertNotIn("CI-only check: markdownlint-cli2-action", run["outputs"][-1])
        self.assertIn(
            "Explicit exceptions: check-vendored-contracts.py, markdownlint-cli2-action",
            run["outputs"][-1],
        )
        self.assertNotIn(
            "findings_are_on_topic",
            run["evaluations"][-1]["unmet_criteria"],
        )
        checks = run["evaluations"][-1]["citation_checks"]
        self.assertGreaterEqual(len(checks), 4)
        self.assertEqual({check["verdict"] for check in checks}, {"verified"})

        manifest = {
            item["path"]: item
            for item in run["evidence_manifest"]["observations"]
        }
        self.assertGreater(manifest["release-check.sh"]["line_end"], 80)
        self.assertGreater(manifest[".github/workflows/tests.yml"]["line_end"], 80)

    def test_target_drift_is_reported_instead_of_hidden_by_release_gate_delegation(self) -> None:
        self._write_release_gate()
        self._write_tests_workflow(ruff_targets="src/")

        run = self._run()

        self.assertEqual(run["stop_reason"], "passed")
        self.assertIn("odeklarerad drift", run["outputs"][-1])
        self.assertIn("target drift for ruff", run["outputs"][-1])
        self.assertIn("tests", run["outputs"][-1])
        self.assertNotIn("CI-only check: check-vendored-contracts.py", run["outputs"][-1])
        self.assertNotIn("CI-only check: markdownlint-cli2-action", run["outputs"][-1])

        relation = (
            'command "ruff" targets differ: '
            'release-check.sh=["src", "tests"]; '
            '.github/workflows/tests.yml=["src"]'
        )
        checks = run["evaluations"][-1]["citation_checks"]
        relation_checks = [
            check for check in checks if check["claim"] == relation
        ]
        self.assertEqual(len(relation_checks), 1)
        self.assertEqual(relation_checks[0]["verdict"], "verified")
        self.assertEqual(
            relation_checks[0]["claim_check"]["checked"]["source_targets"],
            ["src", "tests"],
        )
        self.assertEqual(
            relation_checks[0]["claim_check"]["checked"]["other_targets"],
            ["src"],
        )
        self.assertIn(f"{FACT}  {relation}", render_run_text(run))


if __name__ == "__main__":
    unittest.main()
