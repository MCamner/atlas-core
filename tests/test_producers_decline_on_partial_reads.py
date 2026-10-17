"""A deterministic producer declines when it cannot read what its verdict needs.

These call `produce_repo_review` directly, so an observation can be marked
partial (`read_in_full() is False`) or uncounted (`None`) without depending on
how the observer windows a file. A wrong verdict is worse than no verdict.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import re
import shutil
import tempfile
import unittest

from atlas_core.evidence_base import EvidenceBase
from atlas_core.observation import Observation
from atlas_core.review_plan import build_review_plan
from atlas_core.review_producers import produce_repo_review
from atlas_core.snapshot import collect_observation, take_snapshot
from atlas_core.state import AtlasPlan


GATE_PARITY_TASK = (
    "Kontrollera om release-check.sh och GitHub Actions har samma release-gates. "
    "Identifiera konkret drift mellan release-check.sh, tests.yml, "
    "markdownlint.yml och mq-stack-gate.yml."
)
CI_TASK = (
    "Granska CI-konfigurationen och avgör om Run Atlas Core använder samma "
    "testkommando som den ordinarie test-gaten."
)
CHANGELOG_TASK = (
    "Granska changelog-versionen och avgör om release-heading i CHANGELOG.md "
    "matchar package-versionen i pyproject.toml."
)
METADATA_TASK = (
    "Granska package version metadata och avgör om VERSION, pyproject.toml "
    "och MANIFEST.json är synkroniserade med samma version."
)
TEST_COMMAND = "uv run --locked --group ci python -m unittest discover -s tests"

POLICY = """\
WORKFLOW_SCOPE: dict[str, str | bool] = {
    "tests.yml": True,
    "markdownlint.yml": True,
    "mq-stack-gate.yml": False,  # cross-repo
}

EXCEPTIONS: dict[str, str] = {
    "markdownlint-cli2-action": (
        "CI only action."
    ),
    "check-vendored-contracts.py": "CI only.",
}
"""
GATE = (
    "#!/usr/bin/env bash\n"
    'run_check "pytest" uv run pytest tests/\n'
    'run_check "check-gate-parity.py" uv run python scripts/check-gate-parity.py\n'
)
TESTS_WORKFLOW = (
    "jobs:\n"
    "  test:\n"
    "    steps:\n"
    "      - uses: actions/checkout@v4\n"
    "      - run: uv run pytest tests/\n"
    "      - run: uv run python scripts/check-vendored-contracts.py\n"
    "      - run: uv run python scripts/check-gate-parity.py\n"
    "  release:\n"
    "    steps:\n"
    "      - run: ./release-check.sh\n"
)
MARKDOWNLINT_WORKFLOW = (
    "jobs:\n"
    "  lint:\n"
    "    steps:\n"
    "      - uses: DavidAnson/markdownlint-cli2-action@v20\n"
)


class _ProducerCase(unittest.TestCase):
    task = ""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = self.tmp / "repo"
        self.root.mkdir()

    def _write(self, relative: str, text: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def _produce(
        self,
        paths: list[str],
        *,
        partial: dict[str, int | None] | None = None,
    ) -> str:
        """Run the producers over `paths`.

        `partial` maps a path to the `total_lines` its observation claims:
        a larger count makes the excerpt a partial read, `None` an uncounted
        one.
        """
        snapshot = take_snapshot(self.root)
        observations: list[Observation] = []
        for path in paths:
            observation = collect_observation(snapshot, path)
            if partial is not None and path in partial:
                observation = replace(observation, total_lines=partial[path])
            observations.append(observation)
        plan = AtlasPlan(
            goal=self.task,
            route_name="repo_review",
            steps=[],
            stop_conditions=[],
            validation_focus=[],
            review=build_review_plan(self.task, snapshot.snapshot_id),
        )
        return produce_repo_review(
            self.task,
            plan,
            EvidenceBase(snapshot, observations),
        )


class TestGateParityDeclines(_ProducerCase):
    task = GATE_PARITY_TASK
    paths = [
        "release-check.sh",
        "scripts/check-gate-parity.py",
        ".github/workflows/tests.yml",
        ".github/workflows/markdownlint.yml",
    ]

    def setUp(self) -> None:
        super().setUp()
        self._write("release-check.sh", GATE)
        self._write("scripts/check-gate-parity.py", POLICY)
        self._write(".github/workflows/tests.yml", TESTS_WORKFLOW)
        self._write(".github/workflows/markdownlint.yml", MARKDOWNLINT_WORKFLOW)

    def test_fixture_produces_a_verdict(self) -> None:
        output = self._produce(self.paths)

        self.assertIn("ingen odeklarerad drift", output)

    def test_missing_or_partial_gate_and_workflow_decline(self) -> None:
        for path in self.paths:
            if path == "scripts/check-gate-parity.py":
                continue
            with self.subTest(missing=path):
                self.assertEqual(
                    self._produce([p for p in self.paths if p != path]),
                    "",
                )
            for total in (999, None):
                with self.subTest(partial=path, total_lines=total):
                    self.assertEqual(
                        self._produce(self.paths, partial={path: total}),
                        "",
                    )

    def test_missing_policy_declines(self) -> None:
        self.assertEqual(
            self._produce(self.paths[:1] + self.paths[2:]),
            "",
        )

    def test_unclosed_scope_block_declines(self) -> None:
        """A scope block cut by the read window can hide an enabled workflow."""
        self._write(
            "scripts/check-gate-parity.py",
            'WORKFLOW_SCOPE: dict[str, str | bool] = {\n'
            '    "tests.yml": True,\n'
            '    "markdownlint.yml": True,\n',
        )

        self.assertEqual(self._produce(self.paths), "")

    def test_missing_exceptions_block_declines(self) -> None:
        self._write(
            "scripts/check-gate-parity.py",
            POLICY.split("EXCEPTIONS", 1)[0],
        )

        self.assertEqual(self._produce(self.paths), "")

    def test_unclosed_exceptions_block_declines(self) -> None:
        self._write(
            "scripts/check-gate-parity.py",
            POLICY.rsplit("}", 1)[0],
        )

        self.assertEqual(self._produce(self.paths), "")

    def test_scope_entry_the_parser_cannot_read_declines(self) -> None:
        self._write(
            "scripts/check-gate-parity.py",
            POLICY.replace(
                '    "markdownlint.yml": True,\n',
                '    "markdownlint.yml": True,\n    "extra.yml": ENABLED,\n',
            ),
        )

        self.assertEqual(self._produce(self.paths), "")

    def test_exceptions_entry_the_parser_cannot_read_declines(self) -> None:
        self._write(
            "scripts/check-gate-parity.py",
            POLICY.replace(
                '    "check-vendored-contracts.py": "CI only.",\n',
                '    "check-vendored-contracts.py": "CI only.",\n    **SHARED,\n',
            ),
        )

        self.assertEqual(self._produce(self.paths), "")

    def test_second_scope_definition_declines(self) -> None:
        self._write(
            "scripts/check-gate-parity.py",
            POLICY + 'WORKFLOW_SCOPE = {\n    "tests.yml": False,\n}\n',
        )

        self.assertEqual(self._produce(self.paths), "")

    def test_entry_on_the_opening_line_declines(self) -> None:
        """An entry beside `{` would be skipped by a line-per-entry parser."""
        for name in ("WORKFLOW_SCOPE", "EXCEPTIONS"):
            with self.subTest(block=name):
                self._write(
                    "scripts/check-gate-parity.py",
                    re.sub(
                        rf"^{name}(.*)= \{{$",
                        rf'{name}\1= {{"extra.yml": True,',
                        POLICY,
                        flags=re.MULTILINE,
                    ),
                )
                self.assertEqual(self._produce(self.paths), "")

    def test_literal_forms_the_policy_may_use_still_produce_a_verdict(self) -> None:
        policy = (
            "WORKFLOW_SCOPE = {  # which workflows\n"
            "    'tests.yml': True,\n"
            '    "markdownlint.yml": True,\n'
            '    "mq-stack-gate.yml": False,\n'
            "}  # end of scope\n"
            "\n"
            "EXCEPTIONS = {\n"
            "    'markdownlint-cli2-action': ('CI only action.'),\n"
            '    "check-vendored-contracts.py": (  # long reason\n'
            "        'CI only.',\n"
            "    ),\n"
            '    "other.py": ("one",),\n'
            "}  # end of exceptions\n"
        )
        self._write("scripts/check-gate-parity.py", policy)

        output = self._produce(self.paths)

        self.assertIn("ingen odeklarerad drift", output)
        self.assertIn(
            "Explicit exceptions: check-vendored-contracts.py, "
            "markdownlint-cli2-action, other.py",
            output,
        )

    def test_no_local_checks_declines(self) -> None:
        self._write("release-check.sh", "#!/usr/bin/env bash\necho ok\n")

        self.assertEqual(self._produce(self.paths), "")

    def test_conclusion_names_the_observed_declaration_blocks(self) -> None:
        output = self._produce(self.paths)

        self.assertIn(
            "WORKFLOW_SCOPE och EXCEPTIONS som de står deklarerade",
            output,
        )


class TestCiTestCommandParityDeclines(_ProducerCase):
    task = CI_TASK
    paths = [".github/workflows/test.yml", ".github/workflows/run-atlas.yml"]

    def setUp(self) -> None:
        super().setUp()
        for path in self.paths:
            self._write(
                path,
                f"jobs:\n  test:\n    steps:\n      - run: {TEST_COMMAND}\n",
            )

    def test_fixture_produces_a_verdict(self) -> None:
        self.assertIn("CI test-command parity", self._produce(self.paths))

    def test_missing_or_partial_workflow_declines(self) -> None:
        for path in self.paths:
            with self.subTest(missing=path):
                self.assertEqual(
                    self._produce([p for p in self.paths if p != path]),
                    "",
                )
            for total in (999, None):
                with self.subTest(partial=path, total_lines=total):
                    self.assertEqual(
                        self._produce(self.paths, partial={path: total}),
                        "",
                    )

    def test_no_test_command_in_the_gate_declines(self) -> None:
        self._write(
            self.paths[0],
            "jobs:\n  test:\n    steps:\n      - run: echo ok\n",
        )

        self.assertEqual(self._produce(self.paths), "")


class TestReleaseChangelogParityDeclines(_ProducerCase):
    task = CHANGELOG_TASK
    paths = ["pyproject.toml", "CHANGELOG.md"]

    def setUp(self) -> None:
        super().setUp()
        self._write("pyproject.toml", '[project]\nname = "demo"\nversion = "1.2.3"\n')
        self._write("CHANGELOG.md", "# Changelog\n\n## v1.2.3\n")

    def test_fixture_produces_a_verdict(self) -> None:
        self.assertIn("Changelog version parity", self._produce(self.paths))

    def test_missing_source_declines(self) -> None:
        for path in self.paths:
            with self.subTest(missing=path):
                self.assertEqual(
                    self._produce([p for p in self.paths if p != path]),
                    "",
                )

    def test_partial_pyproject_declines(self) -> None:
        for total in (999, None):
            with self.subTest(total_lines=total):
                self.assertEqual(
                    self._produce(self.paths, partial={"pyproject.toml": total}),
                    "",
                )

    def test_partial_changelog_window_still_produces_a_verdict(self) -> None:
        """The changelog claim is about the first visible release heading."""
        output = self._produce(self.paths, partial={"CHANGELOG.md": 999})

        self.assertIn("Changelog version parity", output)

    def test_pyproject_without_a_version_declines(self) -> None:
        self._write("pyproject.toml", '[project]\nname = "demo"\n')

        self.assertEqual(self._produce(self.paths), "")


class TestReleaseMetadataParityDeclines(_ProducerCase):
    task = METADATA_TASK
    paths = ["VERSION", "pyproject.toml", "MANIFEST.json"]

    def setUp(self) -> None:
        super().setUp()
        self._write("VERSION", "1.2.3\n")
        self._write("pyproject.toml", '[project]\nname = "demo"\nversion = "1.2.3"\n')
        self._write("MANIFEST.json", '{\n  "version": "1.2.3"\n}\n')

    def test_fixture_produces_a_verdict(self) -> None:
        self.assertIn("Package version metadata parity", self._produce(self.paths))

    def test_missing_or_partial_source_declines(self) -> None:
        for path in self.paths:
            with self.subTest(missing=path):
                self.assertEqual(
                    self._produce([p for p in self.paths if p != path]),
                    "",
                )
            for total in (999, None):
                with self.subTest(partial=path, total_lines=total):
                    self.assertEqual(
                        self._produce(self.paths, partial={path: total}),
                        "",
                    )

    def test_source_without_a_version_declines(self) -> None:
        for path, text in (
            ("VERSION", "unreleased\n"),
            ("MANIFEST.json", '{\n  "name": "demo"\n}\n'),
        ):
            with self.subTest(path=path):
                original = (self.root / path).read_text(encoding="utf-8")
                self._write(path, text)
                self.assertEqual(self._produce(self.paths), "")
                self._write(path, original)


if __name__ == "__main__":
    unittest.main()
