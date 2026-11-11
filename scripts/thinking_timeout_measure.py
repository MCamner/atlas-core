"""v2.2: measure where the time goes when a thinking model answers Atlas.

Read-only. Needs a running Ollama and a model it has:

    python3 scripts/thinking_timeout_measure.py out.jsonl qwen3.5:9b

One JSON object per call, appended as it completes. Three kinds of row:

- `atlas`: the loop from `tests/test_live_smoke.py`, through the real adapter.
  The request is whatever Atlas builds. The transport is wrapped only to copy
  the payload and the provider's own counters out; nothing is changed.
- `replay_think_false`: the payload Atlas sent, posted again with one field
  added, `think: false`. Atlas sends no such field. This row is the
  comparison, not a run of Atlas.
- `atlas_at_timeout`: the same loop at a stated `ATLAS_MODEL_TIMEOUT`, to see
  the timeout itself rather than infer it from a duration.

With `--openai-compatible ENDPOINT` the `atlas` rows go through the
`openai_compatible` adapter instead, the key is read from
`ATLAS_MODEL_API_KEY`, and no replay is made.

The rows carry no endpoint and no key. Results are non-deterministic: a second
run is a second measurement, so write it to a new dated file.
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
from atlas_core.adapters.live_model import (
    PromptLimits,
    UrllibTransport,
    model_adapter_or_raise,
)
from atlas_core.budget import RunLimits
from atlas_core.snapshot import collect_observation, take_snapshot

README = "# Demo\n\npip install demo\n\nKör `demo --help` för att komma igång.\n"
TASK = "granska repot och svara på om README beskriver installation"

REPEATS = 3
#: Long enough that a thinking reply finishes, so its duration is measured
#: instead of cut off.
MEASURE_TIMEOUT = 900.0
#: The timeouts a user meets: the adapter's default and the value
#: `docs/live-smoke.md` recommends.
REPRODUCE_TIMEOUTS = (60.0, 170.0)


class RecordingTransport:
    """Passes every call through unchanged and keeps what went each way."""

    def __init__(self) -> None:
        self._inner = UrllibTransport()
        self.url = ""
        self.payload: dict[str, Any] = {}
        self.reply: dict[str, Any] = {}

    def post(
        self, url: str, payload: dict[str, Any], headers: dict[str, str], timeout: float
    ) -> dict[str, Any]:
        self.url = url
        self.payload = payload
        self.reply = {}
        self.reply = self._inner.post(url, payload, headers, timeout)
        return self.reply


def _seconds(nanoseconds: Any) -> float | None:
    return round(nanoseconds / 1e9, 1) if isinstance(nanoseconds, int) else None


def provider_counters(reply: dict[str, Any]) -> dict[str, Any]:
    """The provider's own account of one reply, lengths instead of text."""
    if "choices" in reply:
        message = (reply.get("choices") or [{}])[0].get("message") or {}
        usage = reply.get("usage") or {}
        return {
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "reasoning_chars": len(str(message.get("reasoning") or "")),
            "content_chars": len(str(message.get("content") or "")),
            "finish_reason": (reply.get("choices") or [{}])[0].get("finish_reason"),
            "system_fingerprint": reply.get("system_fingerprint"),
        }
    return {
        "prompt_tokens": reply.get("prompt_eval_count"),
        "completion_tokens": reply.get("eval_count"),
        "thinking_chars": len(str(reply.get("thinking") or "")),
        "response_chars": len(str(reply.get("response") or "")),
        "load_seconds": _seconds(reply.get("load_duration")),
        "eval_seconds": _seconds(reply.get("eval_duration")),
        "total_seconds": _seconds(reply.get("total_duration")),
    }


def atlas_run(
    kind: str, env: dict[str, str], timeout: float
) -> tuple[dict[str, Any], RecordingTransport]:
    transport = RecordingTransport()
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
            {**env, "ATLAS_MODEL_TIMEOUT": f"{timeout:g}"},
            transport=transport,
            limits=PromptLimits(max_prompt_chars=6_000, max_observation_chars=1_500),
        )
        started = time.monotonic()
        document = AtlasController(max_iterations=1, model_adapter=adapter).run(
            TASK,
            evidence=base,
            json_mode=True,
            limits=RunLimits(
                wall_seconds=timeout + 60.0,
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
        "kind": kind,
        "provider": env["ATLAS_MODEL_PROVIDER"],
        "model": env["ATLAS_MODEL"],
        "request_timeout": timeout,
        "request_fields": sorted(transport.payload),
        "prompt_chars": len(json.dumps(transport.payload, ensure_ascii=False)),
        "wall_seconds": elapsed,
        "stop_reason": document["stop_reason"],
    }
    result = document["metadata"].get("model_result")
    if result is None:
        row["reply"] = "none"
        row["failure"] = document["metadata"].get("failure")
        return row, transport
    metadata = result["metadata"]
    evaluation = document["evaluations"][-1]
    row.update(
        {
            "reply": "received",
            "provider_model": metadata.get("provider_model"),
            "output_schema_sent": metadata.get("output_schema_sent"),
            "output_conformed": metadata.get("output_conformed"),
            "output_schema_gap": metadata.get("output_schema_gap"),
            "usage_tokens": metadata.get("usage_tokens"),
            "passed": evaluation["passed"],
            "evidence_gaps": evaluation["evidence_gaps"],
            "counters": provider_counters(transport.reply),
        }
    )
    return row, transport


def replay_think_false(
    model: str, url: str, payload: dict[str, Any]
) -> dict[str, Any]:
    started = time.monotonic()
    row: dict[str, Any] = {
        "kind": "replay_think_false",
        "provider": "ollama",
        "model": model,
        "request_timeout": MEASURE_TIMEOUT,
        "request_fields": sorted({**payload, "think": False}),
    }
    try:
        reply = UrllibTransport().post(
            url, {**payload, "think": False}, {}, MEASURE_TIMEOUT
        )
    except Exception as exc:  # noqa: BLE001
        row.update({"reply": "none", "error": type(exc).__name__})
    else:
        row.update({"reply": "received", "counters": provider_counters(reply)})
    row["wall_seconds"] = round(time.monotonic() - started, 1)
    return row


def main(argv: list[str]) -> int:
    args = argv[1:]
    endpoint = ""
    if "--openai-compatible" in args:
        at = args.index("--openai-compatible")
        endpoint = args[at + 1]
        del args[at : at + 2]
    if len(args) != 2:
        print(__doc__)
        return 2
    out, model = Path(args[0]), args[1]

    if endpoint:
        env = {
            "ATLAS_MODEL_PROVIDER": "openai_compatible",
            "ATLAS_MODEL": model,
            "ATLAS_MODEL_ENDPOINT": endpoint,
            "ATLAS_MODEL_API_KEY": os.environ.get("ATLAS_MODEL_API_KEY", ""),
        }
    else:
        env = {"ATLAS_MODEL_PROVIDER": "ollama", "ATLAS_MODEL": model}

    with out.open("w", encoding="utf-8") as handle:

        def emit(row: dict[str, Any]) -> None:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()
            print(json.dumps(row, ensure_ascii=False), flush=True)

        for _ in range(REPEATS):
            row, transport = atlas_run("atlas", env, MEASURE_TIMEOUT)
            emit(row)
            if not endpoint and transport.payload:
                emit(replay_think_false(model, transport.url, transport.payload))
        if not endpoint:
            for timeout in REPRODUCE_TIMEOUTS:
                emit(atlas_run("atlas_at_timeout", env, timeout)[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
