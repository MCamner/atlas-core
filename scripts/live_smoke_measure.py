"""P1.2 box three: the live smoke measurement behind `docs/live-smoke.md`.

Read-only, and reproducible:

    ollama serve                      # or have it running already
    python3 scripts/live_smoke_measure.py runs.jsonl qwen3:4b-instruct llama3.2:latest

One JSON object per run, appended as it completes. The table in
`docs/live-smoke.md` is derived from such a file rather than from anything
anybody remembered — the first version of that table was assembled by hand
across three ad-hoc batches with different output truncation, and its totals
disagreed with its own rows.

Nothing is written outside the temporary fixture this creates for each run. The
findings are the model's, and what is measured is whether the loop establishes
or refuses them. See `docs/live-smoke.md` for the result and its limits, and
`tests/test_live_smoke.py` for the assertions that make a run pass or fail.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from atlas_core import AtlasController, EvidenceBase
from atlas_core.adapters.live_model import PromptLimits, model_adapter_or_raise
from atlas_core.budget import RunLimits
from atlas_core.snapshot import collect_observation, take_snapshot

#: Small on purpose. A smoke measurement that needs a large prompt is measuring
#: the provider's context window, which is not the question.
README = "# Demo\n\npip install demo\n\nKör `demo --help` för att komma igång.\n"
TASK = "granska repot och svara på om README beskriver installation"

DEFAULT_MODELS = ("qwen3:4b-instruct", "llama3.2:latest", "mq-learn:latest")
REPEATS = 3
#: Bounds the worst case. A provider that does not answer is a result, and one
#: that takes ten minutes to say so is not a more interesting one.
REQUEST_TIMEOUT = "120"


def one_run(model: str) -> dict[str, Any]:
    """One loop against one fresh fixture. Never raises for a provider failure:
    a run that got no reply is a row, not a crash."""
    os.environ["ATLAS_MODEL_PROVIDER"] = "ollama"
    os.environ["ATLAS_MODEL"] = model
    os.environ["ATLAS_MODEL_TIMEOUT"] = REQUEST_TIMEOUT

    tmp = tempfile.mkdtemp()
    try:
        root = Path(tmp)
        (root / "README.md").write_text(README, encoding="utf-8")
        snapshot = take_snapshot(root)
        base = EvidenceBase(
            snapshot=snapshot,
            observations=[collect_observation(snapshot, "README.md", max_lines=10)],
        )
        adapter = model_adapter_or_raise(
            limits=PromptLimits(max_prompt_chars=6_000, max_observation_chars=1_500)
        )
        started = time.monotonic()
        document = AtlasController(max_iterations=1, model_adapter=adapter).run(
            TASK,
            evidence=base,
            json_mode=True,
            limits=RunLimits(
                wall_seconds=180.0,
                model_calls=2,
                tool_calls=0,
                tokens=200_000,
                output_bytes=200_000,
            ),
        )
        elapsed = round(time.monotonic() - started, 1)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    row: dict[str, Any] = {
        "model": model,
        "wall_seconds": elapsed,
        "stop_reason": document["stop_reason"],
    }
    result = document["metadata"].get("model_result")
    if result is None:
        # No reply at all. Recorded as its own kind rather than as a missing
        # field, because "did not answer" is the result.
        row["reply"] = "none"
        row["failure"] = document["metadata"].get("failure")
        return row

    metadata = result["metadata"]
    evaluation = document["evaluations"][-1]
    row.update(
        {
            "reply": "received",
            "provider_model": metadata.get("provider_model"),
            "output_schema_sent": metadata.get("output_schema_sent"),
            "output_conformed": metadata.get("output_conformed"),
            "output_schema_gap": metadata.get("output_schema_gap"),
            "usage_tokens": (
                int(metadata["usage_tokens"]) if "usage_tokens" in metadata else None
            ),
            "determinism": metadata.get("determinism"),
            "non_deterministic": document["metadata"].get("non_deterministic"),
            "tools_declared": metadata.get("tools_declared"),
            "tools_invoked": metadata.get("tools_invoked"),
            "passed": evaluation["passed"],
            "evidence_gaps": evaluation["evidence_gaps"],
            "next_action": (evaluation.get("next_action") or {}).get("kind"),
            "citation_verdicts": [
                check["verdict"] for check in evaluation.get("citation_checks", [])
            ],
            "citations_sound": [
                check["citations_are_sound"]
                for check in evaluation.get("citation_checks", [])
            ],
        }
    )
    return row


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    out = Path(argv[1])
    models = argv[2:] or list(DEFAULT_MODELS)

    with out.open("w", encoding="utf-8") as handle:
        for model in models:
            for _ in range(REPEATS):
                try:
                    row = one_run(model)
                except Exception as exc:  # noqa: BLE001
                    # The harness failing is not the provider failing, and a row
                    # that did not distinguish them would be worse than none.
                    row = {
                        "model": model,
                        "reply": "none",
                        "harness_error": type(exc).__name__,
                    }
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                handle.flush()
                print(json.dumps(row, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
