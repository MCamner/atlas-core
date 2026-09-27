from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import unittest


TASK = (
    "Granska atlas-core och hitta P0/P1/P2 förbättringar. Prioritera den "
    "viktigaste verifierbara bristen som stöds av filer du faktiskt läser. "
    "Ange källan och varför den spelar roll. Om evidensen inte räcker, säg "
    "det i stället för att gissa."
)


class TestAtlasLoopEndToEndSmoke(unittest.TestCase):
    def test_repo_review_loop_produces_bounded_structured_result(self) -> None:
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
        try:
            run = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            self.fail(
                "atlas did not emit valid JSON: "
                f"{exc}; stdout={completed.stdout[-4000:]}; "
                f"stderr={completed.stderr[-2000:]}"
            )

        print(
            "ATLAS_LOOP_SMOKE_RESULT="
            + json.dumps(
                {
                    "returncode": completed.returncode,
                    "schema": run.get("schema"),
                    "status": run.get("status"),
                    "stop_reason": run.get("stop_reason"),
                    "iteration": run.get("iteration"),
                    "route": run.get("route"),
                    "plan": run.get("plan"),
                    "observations": run.get("observations"),
                    "outputs": run.get("outputs"),
                    "evaluations": run.get("evaluations"),
                    "metadata": run.get("metadata"),
                },
                ensure_ascii=False,
            )
        )

        self.assertEqual(run.get("schema"), "atlas-run.v1")
        self.assertIsNotNone(run.get("route"))
        self.assertEqual(run["route"].get("name"), "repo_review")
        self.assertGreaterEqual(run.get("iteration", 0), 1)
        self.assertTrue(run.get("observations"), msg="repo run observed no sources")
        self.assertNotIn(
            run.get("stop_reason"),
            {"tool_error", "cancelled", "budget_exhausted", "approval_required"},
        )
        self.assertNotEqual(run.get("status"), "failed")
        if run.get("evaluations"):
            self.assertFalse(run["evaluations"][-1].get("requires_user_approval"))


if __name__ == "__main__":
    unittest.main()
