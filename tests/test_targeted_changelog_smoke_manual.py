from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import unittest


TASK = (
    "Granska changelog-versionen i atlas-core och avgör om release-heading "
    "i CHANGELOG.md matchar package-versionen i pyproject.toml. "
    "Ange källorna och gissa inte."
)


class TestTargetedChangelogSmoke(unittest.TestCase):
    def test_real_repo_finds_release_heading_beyond_first_window(self) -> None:
        root = Path(__file__).resolve().parents[1]
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "atlas_core.cli",
                "run",
                TASK,
                "--repo-path",
                str(root),
                "--json",
            ],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
        self.assertTrue(
            completed.stdout.strip(),
            msg=f"atlas emitted no JSON; stderr={completed.stderr[-2000:]}",
        )
        run = json.loads(completed.stdout)
        checks = (run.get("evaluations") or [{}])[-1].get("citation_checks") or []
        changelog = next(
            item
            for item in run["evidence_manifest"]["observations"]
            if item["path"] == "CHANGELOG.md"
        )

        print(
            "TARGETED_CHANGELOG_SMOKE="
            + json.dumps(
                {
                    "returncode": completed.returncode,
                    "status": run.get("status"),
                    "stop_reason": run.get("stop_reason"),
                    "iteration": run.get("iteration"),
                    "route": run.get("route"),
                    "review": (run.get("plan") or {}).get("review"),
                    "changelog_range": [
                        changelog.get("line_start"),
                        changelog.get("line_end"),
                        changelog.get("total_lines"),
                    ],
                    "rounds": (run.get("metadata") or {}).get("observation_rounds"),
                    "citation_verdicts": [
                        {
                            "claim": item.get("claim"),
                            "verdict": item.get("verdict"),
                            "path": (
                                ((item.get("claim_check") or {}).get("checked") or {})
                                .get("path")
                            ),
                        }
                        for item in checks
                    ],
                },
                ensure_ascii=False,
            )
        )

        self.assertEqual(run.get("schema"), "atlas-run.v1")
        self.assertEqual((run.get("route") or {}).get("name"), "repo_review")
        self.assertEqual(
            ((run.get("plan") or {}).get("review") or {}).get("topic"),
            "release_changelog",
        )
        self.assertEqual(run.get("stop_reason"), "passed")
        self.assertEqual(run.get("iteration"), 2)
        self.assertEqual(changelog.get("line_start"), 1302)
        self.assertEqual(changelog.get("total_lines"), 1352)
        self.assertEqual(len(checks), 2)
        self.assertEqual({item.get("verdict") for item in checks}, {"verified"})
        self.assertEqual(
            {
                ((item.get("claim_check") or {}).get("checked") or {}).get("path")
                for item in checks
            },
            {"CHANGELOG.md", "pyproject.toml"},
        )


if __name__ == "__main__":
    unittest.main()
