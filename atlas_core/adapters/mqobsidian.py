from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any


class MQObsidianMemoryAdapter:
    """Read compact mqobsidian context and write Atlas candidates only."""

    _MAX_SURFACE_CHARS = 4_000

    def __init__(self, vault_path: str | Path, *, project: str):
        self.vault_path = Path(vault_path)
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", project):
            raise ValueError("project must be a single directory-safe name")
        self.project = project

    def read(self, query: str) -> list[str]:
        relative_paths = (
            Path(".mq/context/task-pack.md"),
            Path("memory/learn/agent") / f"{self.project}.md",
            Path("systems") / self.project / "hot.md",
            Path("systems") / self.project / "index.md",
            Path("memory/context-cards") / f"{self.project}-card.md",
        )
        observations: list[str] = []
        for relative_path in relative_paths:
            path = self.vault_path / relative_path
            if not path.is_file():
                continue
            content = path.read_text(encoding="utf-8")[: self._MAX_SURFACE_CHARS]
            if relative_path == Path(".mq/context/task-pack.md"):
                metadata = self._frontmatter(content)
                if metadata.get("repo") != self.project or metadata.get("task") != query:
                    continue
            observations.append(
                "Durable memory (not runtime truth; verify current claims in source)\n"
                f"{relative_path.as_posix()}:\n{content}"
            )
        return observations

    @staticmethod
    def _frontmatter(content: str) -> dict[str, str]:
        lines = content.splitlines()
        if not lines or lines[0].strip() != "---":
            return {}
        metadata: dict[str, str] = {}
        for line in lines[1:]:
            if line.strip() == "---":
                break
            key, separator, value = line.partition(":")
            if separator:
                metadata[key.strip()] = value.strip()
        return metadata

    def write(self, record: dict[str, Any]) -> str:
        if record.get("schema") != "atlas-memory-candidate.v1":
            raise ValueError("mqobsidian adapter only writes atlas-memory-candidate.v1 records")
        created_at = str(record.get("created_at", "record"))
        filename_stem = re.sub(r"[^A-Za-z0-9._-]", "_", created_at)
        while ".." in filename_stem:
            filename_stem = filename_stem.replace("..", "_")
        filename = filename_stem + ".json"
        candidate_dir = self.vault_path / "inbox" / "atlas-memory-candidates"
        candidate_dir.mkdir(parents=True, exist_ok=True)
        path = candidate_dir / filename
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(path)
