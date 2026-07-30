from __future__ import annotations
from pathlib import Path
import json

class LocalMemoryAdapter:
    def __init__(self, memory_dir: str):
        self.memory_dir = Path(memory_dir)
        self.memory_dir.mkdir(parents=True, exist_ok=True)
    def read(self, query: str) -> list[str]:
        query_l = query.lower()
        results: list[str] = []
        for path in sorted(self.memory_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            haystack = json.dumps(data, ensure_ascii=False).lower()
            if query_l in haystack:
                results.append(data.get("summary", str(data))[:500])
        return results
    def write(self, record: dict) -> str:
        name = record.get("created_at", "record").replace(":", "-").replace("+", "_") + ".json"
        path = self.memory_dir / name
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(path)
