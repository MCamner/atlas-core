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
    "Granska release-versionerna och avgör om VERSION, pyproject.toml, "
    "MANIFEST.json och CHANGELOG.md är synkroniserade med samma version. "
    "Ange källorna och gissa inte om något är tvetydigt."
)
LIMITS = RunLimits(
    wall_seconds=30,
    model_calls=0,
    tool_calls=16,
    tokens=0,
    output_bytes=400_000,
)


class TestDeterministicReleaseVersionReview(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = self.tmp / "repo"
        self.root.mkdir()

    def _write_release_sources(
        self,
        *,
        version: str = "1.2.3",
        manifest_version: str | None = None,
        pyproject_extra_version: str | None = None,
    ) -> None:
        manifest_version = manifest_version or version
        (self.root / "VERSION").write_text(version + "\n", encoding="utf-8")
        pyproject = [
            "[build-system]",
            'requires = ["setuptools"]',
            "",
            "[project]",
            'name = "demo"',
            f'version = "{version}"',
        ]
        if pyproject_extra_version is not None:
            pyproject.append(f'version = "{pyproject_extra_version}"')
        (self.root / "pyproject.toml").write_text(
            "\n".join(pyproject) + "\n",
            encoding="utf-8",
        )
        (self.root / "MANIFEST.json").write_text(
            '{\n  "name": "demo",\n'
            f'  "version": "{manifest_version}"\n'
            '}\n',
            encoding="utf-8",
        )
        (self.root / "CHANGELOG.md").write_text(
            "# Changelog\n\n"
            "## Unreleased\n\n"
            f"## v{version} — 2026-09-27\n"
            "- current release\n\n"
            "## v1.0.0 — 2026-01-01\n"
            "- older release\n",
            encoding="utf-8",
        )
        (self.root / "README.md").write_text("# Demo\n", encoding="utf-8")

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

    def test_matching_versions_become_four_verified_findings(self) -> None:
        self._write_release_sources()

        run = self._run()

        self.assertEqual(run["route"]["name"], "repo_review")
        self.assertEqual(run["plan"]["review"]["topic"], "release")
        self.assertEqual(run["stop_reason"], "passed")
        self.assertEqual(run["iteration"], 1)
        self.assertIn(
            "anger samma version: `1.2.3`",
            run["outputs"][-1],
        )

        checks = run["evaluations"][-1]["citation_checks"]
        self.assertEqual(len(checks), 4)
        self.assertEqual({check["verdict"] for check in checks}, {"verified"})
        self.assertEqual(
            {
                check["claim_check"]["checked"]["path"]
                for check in checks
            },
            {
                "VERSION",
                "pyproject.toml",
                "MANIFEST.json",
                "CHANGELOG.md",
            },
        )

    def test_mismatch_is_reported_from_verified_source_facts(self) -> None:
        self._write_release_sources(manifest_version="9.9.9")

        run = self._run()

        self.assertEqual(run["stop_reason"], "passed")
        self.assertIn("releaseversionerna skiljer sig", run["outputs"][-1])
        checks = run["evaluations"][-1]["citation_checks"]
        self.assertEqual(len(checks), 4)
        self.assertEqual({check["verdict"] for check in checks}, {"verified"})

    def test_ambiguous_project_version_fails_closed(self) -> None:
        self._write_release_sources(pyproject_extra_version="9.9.9")

        run = self._run()

        self.assertNotEqual(run["stop_reason"], "passed")
        self.assertEqual(run["evaluations"][-1]["citation_checks"], [])
        self.assertNotIn("Release version parity", run["outputs"][-1])


if __name__ == "__main__":
    unittest.main()
