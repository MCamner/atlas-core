from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
import unittest

from atlas_core import AtlasController
from atlas_core.adapters.filesystem_repo import FilesystemRepoObserver
from atlas_core.budget import RunLimits
from atlas_core.evidence_base import EvidenceBase
from atlas_core.observer import merge_observations
from atlas_core.snapshot import collect_observation, take_snapshot


TASK = (
    "Granska changelog-versionen och avgör om release-heading i CHANGELOG.md "
    "matchar package-versionen i pyproject.toml. Ange källorna och gissa inte."
)
LIMITS = RunLimits(
    wall_seconds=30,
    model_calls=0,
    tool_calls=16,
    tokens=0,
    output_bytes=400_000,
)


class TestTargetedLineRanges(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = self.tmp / "repo"
        self.root.mkdir()

    def _write_long_file(self, *, heading_line: int) -> None:
        lines = ["# Changelog", "", "## Unreleased", ""]
        while len(lines) < heading_line - 1:
            lines.append(f"- pending note {len(lines) + 1}")
        lines.append("## v1.2.3 — 2026-09-27")
        lines.extend(["- release note", "- another note"])
        (self.root / "CHANGELOG.md").write_text(
            "\n".join(lines) + "\n",
            encoding="utf-8",
        )
        (self.root / "pyproject.toml").write_text(
            "[project]\n"
            'name = "demo"\n'
            'version = "1.2.3"\n',
            encoding="utf-8",
        )

    def _run(self, *, max_iterations: int = 2) -> dict:
        snapshot = take_snapshot(self.root)
        return AtlasController(max_iterations=max_iterations).run(
            TASK,
            evidence=EvidenceBase(snapshot),
            observer=FilesystemRepoObserver(self.root),
            read_first=True,
            limits=LIMITS,
            json_mode=True,
        )

    def test_collect_observation_reads_requested_window_with_full_digest(self) -> None:
        self._write_long_file(heading_line=95)
        snapshot = take_snapshot(self.root)

        head = collect_observation(
            snapshot,
            "CHANGELOG.md",
            max_lines=80,
        )
        tail = collect_observation(
            snapshot,
            "CHANGELOG.md",
            anchor_prefix="## v",
            max_lines=20,
        )
        anchored = collect_observation(
            snapshot,
            "CHANGELOG.md",
            anchor_prefix="## v",
            max_lines=20,
        )

        self.assertEqual(head.content_sha256, tail.content_sha256)
        self.assertEqual(head.content_sha256, anchored.content_sha256)
        self.assertEqual((head.line_start, head.line_end), (1, 80))
        self.assertEqual((tail.line_start, tail.line_end), (81, 97))
        self.assertEqual((anchored.line_start, anchored.line_end), (95, 97))
        self.assertIn("## v1.2.3", anchored.excerpt)
        self.assertFalse(head.read_in_full())
        self.assertFalse(tail.read_in_full())
        self.assertFalse(anchored.read_in_full())

    def test_same_bytes_new_window_is_reframed_not_superseded(self) -> None:
        self._write_long_file(heading_line=95)
        snapshot = take_snapshot(self.root)
        head = collect_observation(
            snapshot,
            "CHANGELOG.md",
            max_lines=80,
        )
        tail = collect_observation(
            snapshot,
            "CHANGELOG.md",
            line_start=81,
            max_lines=20,
        )

        merged, round_result = merge_observations(
            snapshot,
            [head],
            [tail],
        )

        self.assertTrue(round_result.has_new_material)
        self.assertEqual(round_result.added, [])
        self.assertEqual(round_result.superseded, [])
        self.assertEqual(len(round_result.reframed), 1)
        reframed = round_result.reframed[0]
        self.assertEqual(
            (
                reframed.path,
                reframed.previous_line_start,
                reframed.previous_line_end,
                reframed.new_line_start,
                reframed.new_line_end,
            ),
            ("CHANGELOG.md", 1, 80, 95, 97),
        )
        self.assertEqual(len(merged), 1)
        self.assertEqual((merged[0].line_start, merged[0].line_end), (95, 97))

    def test_loop_reads_second_window_and_verifies_changelog_version(self) -> None:
        self._write_long_file(heading_line=95)

        run = self._run()

        self.assertEqual(run["route"]["name"], "repo_review")
        self.assertEqual(run["plan"]["review"]["topic"], "release_changelog")
        self.assertEqual(run["stop_reason"], "passed")
        self.assertEqual(run["iteration"], 2)
        self.assertIn(
            "CHANGELOG-versionen `1.2.3` matchar package-versionen `1.2.3`",
            run["outputs"][-1],
        )

        checks = run["evaluations"][-1]["citation_checks"]
        self.assertEqual(len(checks), 2)
        self.assertEqual({check["verdict"] for check in checks}, {"verified"})
        self.assertEqual(
            {
                check["claim_check"]["checked"]["path"]
                for check in checks
            },
            {"CHANGELOG.md", "pyproject.toml"},
        )

        rounds = run["metadata"]["observation_rounds"]
        self.assertEqual(len(rounds), 2)
        self.assertEqual(
            rounds[1]["line_windows"],
            [{
                "path": "CHANGELOG.md",
                "line_start": 1,
                "max_lines": 80,
                "anchor_prefix": "## v",
            }],
        )
        self.assertEqual(len(rounds[1]["reframed"]), 1)
        self.assertEqual(
            (
                rounds[1]["reframed"][0]["previous_line_start"],
                rounds[1]["reframed"][0]["previous_line_end"],
                rounds[1]["reframed"][0]["new_line_start"],
                rounds[1]["reframed"][0]["new_line_end"],
            ),
            (1, 80, 95, 97),
        )

    def test_missing_anchor_fails_closed_without_widening_evidence(self) -> None:
        lines = ["# Changelog", "", "## Unreleased", ""]
        while len(lines) < 200:
            lines.append(f"- pending note {len(lines) + 1}")
        (self.root / "CHANGELOG.md").write_text(
            "\n".join(lines) + "\n",
            encoding="utf-8",
        )
        (self.root / "pyproject.toml").write_text(
            "[project]\n"
            'name = "demo"\n'
            'version = "1.2.3"\n',
            encoding="utf-8",
        )

        run = self._run(max_iterations=2)

        self.assertEqual(run["stop_reason"], "blocked")
        self.assertEqual(run["iteration"], 1)
        changelog = next(
            item
            for item in run["evidence_manifest"]["observations"]
            if item["path"] == "CHANGELOG.md"
        )
        self.assertEqual(
            (changelog["line_start"], changelog["line_end"]),
            (1, 80),
        )
        self.assertEqual(
            run["evaluations"][-1]["citation_checks"],
            [],
        )


if __name__ == "__main__":
    unittest.main()
