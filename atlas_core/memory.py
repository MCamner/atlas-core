from __future__ import annotations
from pathlib import Path
import json
from datetime import datetime, timezone
from typing import Any

def build_memory_candidate(task: str, route_name: str, output: str, quality_score: float) -> dict[str, Any]:
    return {
        "schema": "atlas-memory-candidate.v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "task": task,
        "route": route_name,
        "quality_score": quality_score,
        "summary": output.strip()[:800],
        "verified": quality_score >= 0.78,
        "public_safe": True,
    }

def save_local_memory(memory_dir: str | None, candidate: dict[str, Any]) -> str | None:
    if not memory_dir:
        return None
    path = Path(memory_dir)
    path.mkdir(parents=True, exist_ok=True)
    filename = candidate["created_at"].replace(":", "-").replace("+", "_") + ".json"
    out = path / filename
    out.write_text(json.dumps(candidate, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(out)
