from __future__ import annotations

import json
import hashlib
from datetime import datetime
from pathlib import Path
import re
from typing import Any, ClassVar


class MQObsidianMemoryAdapter:
    """Read compact mqobsidian context and write Atlas candidates only."""

    _MAX_SURFACE_CHARS = 4_000
    _REQUIRED_FIELDS: ClassVar[
        dict[str, type[Any] | tuple[type[Any], ...]]
    ] = {
        "schema": str,
        "created_at": str,
        "task": str,
        "route": str,
        "quality_score": (int, float),
        "summary": str,
        "verified": bool,
        "public_safe": bool,
    }
    _OPTIONAL_FIELDS = {"saved_path"}

    def __init__(self, vault_path: str | Path, *, project: str):
        self.vault_path = Path(vault_path)
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", project):
            raise ValueError("project must be a single directory-safe name")
        self.project = project

    def _within_vault(self, path: Path) -> Path | None:
        vault = self.vault_path.resolve()
        resolved = path.resolve()
        try:
            resolved.relative_to(vault)
        except ValueError:
            return None
        return resolved

    def read(self, query: str) -> list[str]:
        relative_paths = (
            Path(".mq/context/task-pack.md"),
            Path("memory/learn/agent") / f"{self.project}.md",
            Path("systems") / self.project / "hot.md",
            Path("systems") / self.project / "index.md",
            Path("memory/context-cards") / f"{self.project}-card.md",
        )
        observations: list[str] = []
        seen_digests: set[str] = set()
        for relative_path in relative_paths:
            path = self.vault_path / relative_path
            resolved = self._within_vault(path)
            if resolved is None or not resolved.is_file():
                continue
            content = resolved.read_text(encoding="utf-8")[: self._MAX_SURFACE_CHARS]
            if relative_path == Path(".mq/context/task-pack.md"):
                metadata = self._frontmatter(content)
                if metadata.get("repo") != self.project or metadata.get("task") != query:
                    continue
            digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
            if digest in seen_digests:
                continue
            seen_digests.add(digest)
            observation = (
                "Durable memory (not runtime truth; verify current claims in source)\n"
                f"source={relative_path.as_posix()} sha256:{digest}\n{content}"
            )
            observations.append(observation)
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
        if not isinstance(record, dict) or record.get("schema") != "atlas-memory-candidate.v1":
            raise ValueError("mqobsidian adapter only writes atlas-memory-candidate.v1 records")
        missing = sorted(set(self._REQUIRED_FIELDS) - set(record))
        if missing:
            raise ValueError(f"memory candidate missing required fields: {missing}")
        extra = sorted(set(record) - set(self._REQUIRED_FIELDS) - self._OPTIONAL_FIELDS)
        if extra:
            raise ValueError(f"memory candidate has undeclared fields: {extra}")
        for name, expected in self._REQUIRED_FIELDS.items():
            value = record[name]
            if name == "quality_score" and isinstance(value, bool):
                raise ValueError("memory candidate quality_score must be numeric")
            if not isinstance(value, expected):
                raise ValueError(f"memory candidate {name} has invalid type")
        if not record["summary"]:
            raise ValueError("memory candidate summary cannot be empty")
        if not record["route"]:
            raise ValueError("memory candidate route cannot be empty")
        quality_score = float(record["quality_score"])
        if not 0.0 <= quality_score <= 1.0:
            raise ValueError("memory candidate quality_score must be between 0 and 1")
        try:
            created_at = datetime.fromisoformat(record["created_at"].replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("memory candidate created_at must be an ISO date-time") from exc
        if created_at.tzinfo is None:
            raise ValueError("memory candidate created_at must include a timezone")

        canonical = {
            key: record[key]
            for key in ("task", "route", "quality_score", "summary", "verified", "public_safe")
        }
        canonical["project"] = self.project
        digest = hashlib.sha256(
            json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        observations_dir = self.vault_path / "memory" / "observations"
        parent = self._within_vault(observations_dir.parent)
        if parent is None:
            raise ValueError("mqobsidian observation path escapes the vault")
        observations_dir.mkdir(parents=True, exist_ok=True)
        path = observations_dir / "atlas-core.observations.jsonl"
        if self._within_vault(path) is None:
            raise ValueError("mqobsidian observation path escapes the vault")
        observation_id = f"atlas-{digest}"
        if path.exists():
            for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                try:
                    existing = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"invalid mqobsidian observation JSONL at line {line_number}"
                    ) from exc
                if not isinstance(existing, dict) or existing.get("schema") != "memory-observation.v1":
                    raise ValueError(
                        f"invalid mqobsidian observation schema at line {line_number}"
                    )
                if existing.get("id") == observation_id:
                    return str(path)
        stored = {
            "schema": "memory-observation.v1",
            "id": observation_id,
            "timestamp": record["created_at"],
            "producer": "atlas-core",
            "repository": self.project,
            "workflow": record["route"],
            "title": record["task"] or "Atlas memory candidate",
            "summary": record["summary"],
            "observation": record["summary"],
            "category": "review" if record["route"] == "repo_review" else "learning",
            "confidence": quality_score,
            "evidence": [
                {
                    "source": "atlas-core",
                    "reference": f"atlas-memory-candidate.v1:sha256:{digest}",
                    "excerpt": record["summary"],
                }
            ],
            "tags": ["atlas-core", record["route"]],
            "proposed_memory_key": observation_id,
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(stored, ensure_ascii=False, separators=(",", ":")) + "\n")
        return str(path)
