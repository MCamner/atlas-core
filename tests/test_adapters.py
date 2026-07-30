from pathlib import Path

from atlas_core.adapters.filesystem_repo import FilesystemRepoAdapter
from atlas_core.adapters.github_reader import GitHubRepoAdapter


def test_filesystem_repo_adapter_reads_readme(tmp_path: Path):
    (tmp_path / "README.md").write_text("# Demo\n\nHello", encoding="utf-8")
    obs = FilesystemRepoAdapter(str(tmp_path)).observe("granska repo")
    assert any("README.md" in item for item in obs)


def test_github_repo_adapter_requires_owner_name():
    try:
        GitHubRepoAdapter("not-a-full-name")
    except ValueError as exc:
        assert "owner/name" in str(exc)
    else:
        raise AssertionError("Expected ValueError")
