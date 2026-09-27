from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tarfile
import tomllib
import tarfile
import zipfile
from email.parser import BytesParser
from pathlib import Path
from pathlib import PurePosixPath


class ReleaseIntegrityError(ValueError):
    pass


def _run(command: list[str], *, cwd: Path, env: dict[str, str]) -> str:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        if result.stdout:
            print(result.stdout, file=sys.stderr, end="")
        if result.stderr:
            print(result.stderr, file=sys.stderr, end="")
        raise RuntimeError(f"command failed ({result.returncode}): {command[0]}")
    return result.stdout.strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_sdist(path: Path, *, source_date_epoch: int) -> None:
    normalized = path.with_name(f".{path.name}.normalized")
    with tarfile.open(path, "r:gz") as source:
        members = source.getmembers()
        with normalized.open("wb") as raw_output:
            with gzip.GzipFile(
                filename="",
                mode="wb",
                fileobj=raw_output,
                compresslevel=9,
                mtime=source_date_epoch,
            ) as compressed_output:
                with tarfile.open(
                    fileobj=compressed_output,
                    mode="w",
                    format=tarfile.PAX_FORMAT,
                ) as target:
                    for member in sorted(members, key=lambda item: item.name):
                        canonical = copy.copy(member)
                        canonical.mtime = source_date_epoch
                        canonical.uid = 0
                        canonical.gid = 0
                        canonical.uname = ""
                        canonical.gname = ""
                        canonical.pax_headers = {
                            key: value
                            for key, value in member.pax_headers.items()
                            if key.lower() not in {"atime", "ctime", "mtime"}
                        }
                        content = source.extractfile(member) if member.isfile() else None
                        target.addfile(canonical, content)
    os.replace(normalized, path)


def _normalized_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _exact_pins(requirements: list[str], *, label: str) -> dict[str, str]:
    pins: dict[str, str] = {}
    for requirement in requirements:
        match = re.fullmatch(r"([A-Za-z0-9._-]+)==([A-Za-z0-9.+!-]+)", requirement)
        if match is None:
            raise ValueError(f"{label} requirement is not an exact version pin: {requirement}")
        name, version = match.groups()
        pins[_normalized_name(name)] = version
    return pins


def _check_build_group(project: dict[str, object]) -> None:
    build_system = project["build-system"]
    dependency_groups = project.get("dependency-groups", {})
    if not isinstance(build_system, dict) or not isinstance(dependency_groups, dict):
        raise ValueError("pyproject build-system/dependency-groups has an invalid shape")

    system_pins = _exact_pins(build_system["requires"], label="build-system")
    build_pins = _exact_pins(dependency_groups.get("build", []), label="build group")
    missing = {
        name: version
        for name, version in system_pins.items()
        if build_pins.get(name) != version
    }
    if missing:
        raise ValueError(f"build group must pin every build-system requirement: {missing}")


def _parse_distribution_metadata(content: bytes, *, artifact: str) -> tuple[str, str]:
    message = BytesParser().parsebytes(content)
    name = message.get("Name")
    version = message.get("Version")
    if not name or not version:
        raise ReleaseIntegrityError(f"distribution metadata lacks name/version: {artifact}")
    return name, version


def read_sdist_metadata(path: Path) -> dict[str, str]:
    with tarfile.open(path, "r:gz") as archive:
        members = archive.getmembers()
        files = [member for member in members if member.isfile()]
        roots: set[str] = set()
        for member in members:
            member_path = PurePosixPath(member.name)
            if member_path.is_absolute() or ".." in member_path.parts:
                raise ReleaseIntegrityError(f"unsafe path in sdist: {member.name}")
            if member_path.parts and member.isfile():
                roots.add(member_path.parts[0])

        if len(roots) != 1:
            raise ReleaseIntegrityError(
                f"sdist must have exactly one root directory, got: {sorted(roots)}"
            )

        root = next(iter(roots))
        expected = f"{root}/PKG-INFO"
        candidates = [
            member
            for member in files
            if PurePosixPath(member.name).as_posix() == expected
        ]
        if len(candidates) != 1:
            raise ReleaseIntegrityError(
                f"sdist must contain exactly one root-level {expected}, got {len(candidates)}"
            )

        source = archive.extractfile(candidates[0])
        if source is None:
            raise ReleaseIntegrityError(f"cannot read sdist metadata: {expected}")
        name, version = _parse_distribution_metadata(source.read(), artifact=path.name)
        return {"Name": name, "Version": version}


def _metadata(path: Path) -> tuple[str, str]:
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            metadata_paths = [
                name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
            ]
            if len(metadata_paths) != 1:
                raise ReleaseIntegrityError(f"wheel must contain one METADATA file: {path.name}")
            content = archive.read(metadata_paths[0])
        return _parse_distribution_metadata(content, artifact=path.name)
    if path.name.endswith(".tar.gz"):
        metadata = read_sdist_metadata(path)
        return metadata["Name"], metadata["Version"]
    raise ReleaseIntegrityError(f"unexpected distribution artifact: {path.name}")


def _build_once(
    *,
    root: Path,
    commit: str,
    checkout: Path,
    output: Path,
    env: dict[str, str],
    source_date_epoch: int,
) -> list[Path]:
    _run(["git", "worktree", "add", "--detach", str(checkout), commit], cwd=root, env=env)
    output.mkdir(parents=True, exist_ok=True)
    _run(
        [
            "uv", "sync", "--project", str(checkout), "--locked", "--only-group", "build",
            "--no-install-project",
        ],
        cwd=checkout,
        env=env,
    )
    _run(
        [
            "uv", "run", "--project", str(checkout), "--locked", "--only-group", "build",
            "--no-sync", "python", "-m", "build", "--no-isolation", "--sdist", "--wheel",
            "--outdir", str(output), str(checkout),
        ],
        cwd=checkout,
        env=env,
    )
    artifacts = sorted(path for path in output.iterdir() if path.is_file())
    if len(artifacts) != 2 or not any(path.suffix == ".whl" for path in artifacts) or not any(
        path.name.endswith(".tar.gz") for path in artifacts
    ):
        raise ValueError("build must produce exactly one wheel and one sdist")
    for artifact in artifacts:
        if artifact.name.endswith(".tar.gz"):
            _normalize_sdist(artifact, source_date_epoch=source_date_epoch)
    return artifacts


def _distribution_hashes(artifacts: list[Path], *, package: str, version: str) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for artifact in artifacts:
        name, artifact_version = _metadata(artifact)
        if _normalized_name(name) != _normalized_name(package) or artifact_version != version:
            raise ValueError(
                f"artifact metadata mismatch for {artifact.name}: {name} {artifact_version}"
            )
        result["wheel" if artifact.suffix == ".whl" else "sdist"] = {
            "filename": artifact.name,
            "sha256": _sha256(artifact),
            "size_bytes": artifact.stat().st_size,
        }
    return result


def _archive_members(path: Path) -> dict[str, dict[str, object]]:
    members: dict[str, dict[str, object]] = {}
    if path.name.endswith(".tar.gz"):
        with tarfile.open(path, "r:gz") as archive:
            for tar_member in archive.getmembers():
                details: dict[str, object] = {
                    "size": tar_member.size,
                    "mtime": tar_member.mtime,
                    "type": tar_member.type.decode("ascii", errors="replace"),
                }
                if tar_member.isfile():
                    source = archive.extractfile(tar_member)
                    if source is None:
                        raise ReleaseIntegrityError(f"cannot inspect tar member: {tar_member.name}")
                    details["sha256"] = hashlib.sha256(source.read()).hexdigest()
                members[tar_member.name] = details
        return members

    with zipfile.ZipFile(path) as archive:
        for zip_member in archive.infolist():
            content = archive.read(zip_member.filename)
            members[zip_member.filename] = {
                "size": zip_member.file_size,
                "mtime": zip_member.date_time,
                "sha256": hashlib.sha256(content).hexdigest(),
            }
    return members


def _archive_difference(first: Path, second: Path) -> dict[str, object]:
    first_members = _archive_members(first)
    second_members = _archive_members(second)
    differences: dict[str, dict[str, object]] = {}
    for name in sorted(first_members.keys() | second_members.keys()):
        left = first_members.get(name)
        right = second_members.get(name)
        if left != right:
            changed_fields = sorted(
                key for key in (left or {}).keys() | (right or {}).keys()
                if (left or {}).get(key) != (right or {}).get(key)
            )
            differences[name] = {
                "changed_fields": changed_fields,
                "build_a": left,
                "build_b": right,
            }
    return {
        "changed_member_count": len(differences),
        "members": dict(list(differences.items())[:8]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify reproducible wheel and sdist builds.")
    parser.add_argument("--output-dir", type=Path, default=Path("dist/release-integrity"))
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if status:
        raise RuntimeError("release integrity requires a clean source checkout")

    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    if not isinstance(project, dict):
        raise ValueError("pyproject project table has an invalid shape")
    package = str(project["name"])
    version = str(project["version"])
    _check_build_group(tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8")))
    output_dir = args.output_dir if args.output_dir.is_absolute() else root / args.output_dir
    output_dir = output_dir.resolve()

    commit = _run(["git", "rev-parse", "HEAD"], cwd=root, env=dict(os.environ))
    epoch = _run(["git", "show", "-s", "--format=%ct", commit], cwd=root, env=dict(os.environ))
    environment = dict(os.environ)
    environment.update({"SOURCE_DATE_EPOCH": epoch, "PYTHONHASHSEED": "0", "TZ": "UTC"})
    output_dir.mkdir(parents=True, exist_ok=True)

    worktrees: list[Path] = []
    try:
        with tempfile.TemporaryDirectory(prefix="atlas-release-build-") as temporary:
            temporary_root = Path(temporary)
            first_checkout = temporary_root / "checkout-a"
            second_checkout = temporary_root / "checkout-b"
            worktrees.extend((first_checkout, second_checkout))
            first = _build_once(
                root=root,
                commit=commit,
                checkout=first_checkout,
                output=temporary_root / "dist-a",
                env=environment,
                source_date_epoch=int(epoch),
            )
            second = _build_once(
                root=root,
                commit=commit,
                checkout=second_checkout,
                output=temporary_root / "dist-b",
                env=environment,
                source_date_epoch=int(epoch),
            )
            first_hashes = _distribution_hashes(first, package=package, version=version)
            second_hashes = _distribution_hashes(second, package=package, version=version)
            if first_hashes != second_hashes:
                mismatches = {
                    kind: {
                        "build_a": first_hashes.get(kind),
                        "build_b": second_hashes.get(kind),
                        "archive_difference": _archive_difference(
                            next(path for path in first if path.name == first_hashes[kind]["filename"]),
                            next(path for path in second if path.name == second_hashes[kind]["filename"]),
                        )
                        if kind in first_hashes and kind in second_hashes
                        else None,
                    }
                    for kind in sorted(first_hashes.keys() | second_hashes.keys())
                    if first_hashes.get(kind) != second_hashes.get(kind)
                }
                raise RuntimeError(
                    "reproducibility check failed; artifact digest mismatch: "
                    + json.dumps(mismatches, sort_keys=True)
                )

            for artifact in first:
                shutil.copy2(artifact, output_dir / artifact.name)

            sbom_path = output_dir / f"{package}-{version}.cdx.json"
            _run(
                [
                    "uv", "export", "--project", str(first_checkout), "--locked", "--no-dev",
                    "--format", "cyclonedx1.5", "--preview-features", "sbom-export",
                    "--output-file", str(sbom_path),
                ],
                cwd=first_checkout,
                env=environment,
            )
            sbom = json.loads(sbom_path.read_text(encoding="utf-8"))
            component = sbom.get("metadata", {}).get("component", {})
            if (
                sbom.get("bomFormat") != "CycloneDX"
                or sbom.get("specVersion") != "1.5"
                or component.get("name") != package
                or component.get("version") != version
            ):
                raise ValueError("release SBOM does not identify the built package/version")

            sbom.setdefault("metadata", {}).setdefault("properties", []).extend(
                [
                    {"name": "atlas:source:commit", "value": commit},
                    {"name": "atlas:release:source_date_epoch", "value": epoch},
                    {
                        "name": "atlas:release:wheel_sha256",
                        "value": first_hashes["wheel"]["sha256"],
                    },
                    {
                        "name": "atlas:release:sdist_sha256",
                        "value": first_hashes["sdist"]["sha256"],
                    },
                ]
            )
            sbom_path.write_text(json.dumps(sbom, indent=2) + "\n", encoding="utf-8")
            for worktree in reversed(worktrees):
                subprocess.run(
                    ["git", "worktree", "remove", "--force", str(worktree)],
                    cwd=root,
                    check=True,
                    capture_output=True,
                    text=True,
                )
            worktrees.clear()

        sbom_record = {"filename": sbom_path.name, "sha256": _sha256(sbom_path)}
        report = {
            "schema": "atlas-release-integrity.v1",
            "source_commit": commit,
            "source_date_epoch": int(epoch),
            "package": package,
            "version": version,
            "artifacts": first_hashes,
            "sbom": sbom_record,
        }
        report_path = output_dir / "release-integrity.json"
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2, sort_keys=True))
    finally:
        for worktree in reversed(worktrees):
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(worktree)],
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )
        subprocess.run(
            ["git", "worktree", "prune"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"reproducible build failed closed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc