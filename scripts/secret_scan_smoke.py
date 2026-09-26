from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> int:
    canary_key = "".join(("AKIA", "IOSF", "ODNN", "7EXA", "MPLE"))
    canary = "AWS_ACCESS_KEY_ID=" + canary_key
    result = subprocess.run(
        ["detect-secrets", "scan", "--no-verify", "--string", canary],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print("detect-secrets canary scan failed", file=sys.stderr)
        return 1

    detections = {
        name.strip(): value.strip()
        for line in result.stdout.splitlines()
        if ":" in line
        for name, value in [line.split(":", maxsplit=1)]
    }
    if detections.get("AWSKeyDetector") != "True":
        print("detect-secrets did not detect the synthetic AWS canary", file=sys.stderr)
        return 1

    repository_root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as directory:
        canary_path = Path(directory) / "canary.env"
        canary_path.write_text(canary + "\n", encoding="utf-8")
        hook_result = subprocess.run(
            [
                "detect-secrets-hook",
                "--baseline",
                str(repository_root / ".secrets.baseline"),
                str(canary_path),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
    if hook_result.returncode == 0:
        print("detect-secrets-hook did not reject the synthetic canary", file=sys.stderr)
        return 1

    print("detect-secrets detected and rejected the synthetic AWS canary")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())