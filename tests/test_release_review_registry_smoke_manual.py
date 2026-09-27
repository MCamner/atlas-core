from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import unittest


TASK = (
    "Granska release-versionerna i atlas-core och avgör om VERSION, "
    "pyproject.toml, MANIFEST.json och CHANGELOG.md är synkroniserade med "
    "samma version. Ange källorna och gissa inte om något är tvetydigt."
)


class TestReleaseReviewRegistrySmoke(unittest.TestCase):
    def test_real_repo_release_versions_are_verified(self) -> None:
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

        print(
            "RELEASE_REVIEW_REGISTRY_SMOKE="
            + json.dumps(
                {
                    "returncode": completed.returncode,
                    "status": run.get("status"),
                    "stop_reason": run.get("stop_reason"),
                    "iteration": run.get("iteration"),
                    "route": run.get("route"),
                    "review": (run.get("plan") or {}).get("review"),
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
            "release",
        )
        self.assertEqual(run.get("stop_reason"), "passed")
        self.assertEqual(run.get("iteration"), 1)
        self.assertEqual(len(checks), 4)
        self.assertEqual({item.get("verdict") for item in checks}, {"verified"})
        self.assertEqual(
            {
                ((item.get("claim_check") or {}).get("checked") or {}).get("path")
                for item in checks
            },
            {
                "VERSION",
                "pyproject.toml",
                "MANIFEST.json",
                "CHANGELOG.md",
            },
        )
        self.assertIn(
            "anger samma version",
            (run.get("outputs") or [""])[-1],
        )


if __name__ == "__main__":
    unittest.main()
