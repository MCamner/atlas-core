from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import unittest


TASK = (
    "Granska CI-konfigurationen i atlas-core och avgör om Run Atlas Core "
    "använder samma testkommando som den ordinarie test-gaten. Ange exakt "
    "vilka workflow-filer som stöder svaret. Om underlaget inte räcker, säg "
    "det i stället för att gissa."
)


class TestRouterFixSmoke(unittest.TestCase):
    def test_named_atlas_ci_review_routes_end_to_end(self) -> None:
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

        print(
            "ROUTER_FIX_SMOKE="
            + json.dumps(
                {
                    "returncode": completed.returncode,
                    "status": run.get("status"),
                    "stop_reason": run.get("stop_reason"),
                    "iteration": run.get("iteration"),
                    "route": run.get("route"),
                    "review": (run.get("plan") or {}).get("review"),
                },
                ensure_ascii=False,
            )
        )

        self.assertEqual(run.get("schema"), "atlas-run.v1")
        self.assertEqual((run.get("route") or {}).get("name"), "repo_review")
        self.assertEqual(
            ((run.get("plan") or {}).get("review") or {}).get("topic"),
            "ci",
        )
        self.assertGreaterEqual(run.get("iteration", 0), 1)
        self.assertNotIn(
            run.get("stop_reason"),
            {"tool_error", "cancelled", "approval_required"},
        )
        if run.get("evaluations"):
            self.assertFalse(run["evaluations"][-1].get("requires_user_approval"))


if __name__ == "__main__":
    unittest.main()
