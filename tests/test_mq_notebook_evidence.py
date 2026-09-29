from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from atlas_core.adapters.mq_notebook import MQNotebookEvidenceWorkspace
from atlas_core.finding import EvidenceRef, Finding, check_finding


def _workspace(root: Path, *, truncated: bool = False, role: str = "source") -> Path:
    sources = root / "sources"
    sources.mkdir(parents=True)
    text = "alpha\nbeta\n"
    source = sources / "001-source.txt"
    source.write_text(text, encoding="utf-8")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    manifest = {
        "schema": "atlas-notebook-evidence-workspace.v1",
        "claim": "alpha exists",
        "retrieval_status": "EVIDENCE_READY",
        "source_count": 1,
        "excluded_truncated": 0,
        "sources": [
            {
                "path": "sources/001-source.txt",
                "captured_sha256": digest,
                "drive_item_id": "drive-1",
                "item_id": "item-1",
                "notebook_id": "nb-1",
                "notebook_title": "Notebook",
                "title": "Source",
                "mime_type": "text/markdown",
                "archive_content_sha256": digest,
                "capture_truncated": truncated,
                "source_role": role,
            }
        ],
        "limitations": [],
    }
    (root / "atlas-notebook-evidence.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    return root


def test_notebook_workspace_produces_context_and_strict_evidence(tmp_path: Path):
    root = _workspace(tmp_path / "workspace")

    context, base = MQNotebookEvidenceWorkspace(root).load()

    assert len(context) == 1
    assert "drive-1" in context[0]
    assert len(base.observations) == 1
    observation = base.observations[0]
    assert observation.path == "sources/001-source.txt"
    assert observation.read_in_full() is True

    finding = Finding.create(
        claim="alpha exists",
        scope=observation.path,
        severity="P2",
        severity_rationale="test",
        evidence=[
            EvidenceRef(
                source_id=observation.source_id,
                content_sha256=observation.content_sha256,
                line_start=1,
                line_end=1,
                quoted="alpha",
            )
        ],
    )
    checked = check_finding(
        finding,
        base.observations,
        base.root,
        readers=base.readers,
    )
    assert checked.citations_are_sound() is True


def test_notebook_workspace_refuses_tampered_capture(tmp_path: Path):
    root = _workspace(tmp_path / "workspace")
    (root / "sources" / "001-source.txt").write_text(
        "tampered\n", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="hash mismatch"):
        MQNotebookEvidenceWorkspace(root).load()


@pytest.mark.parametrize(
    ("truncated", "role", "message"),
    [
        (True, "source", "truncated"),
        (False, "derived", "source-role"),
    ],
)
def test_notebook_workspace_never_promotes_unsafe_capture(
    tmp_path: Path, truncated: bool, role: str, message: str
):
    root = _workspace(
        tmp_path / f"workspace-{role}-{truncated}",
        truncated=truncated,
        role=role,
    )

    with pytest.raises(ValueError, match=message):
        MQNotebookEvidenceWorkspace(root).load()


def test_notebook_workspace_refuses_source_count_drift(tmp_path: Path):
    root = _workspace(tmp_path / "workspace")
    manifest_path = root / "atlas-notebook-evidence.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["source_count"] = 2
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="source_count"):
        MQNotebookEvidenceWorkspace(root).load()
