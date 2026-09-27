from __future__ import annotations

import json
import re
from collections.abc import Callable

from .claim_check import ClaimKind, TypedClaim
from .evidence import FINDINGS_FENCE
from .evidence_base import EvidenceBase
from .observation import Observation
from .state import AtlasPlan


Producer = Callable[[str, AtlasPlan, EvidenceBase], str]

_TEST_COMMAND_MARKERS = ("unittest", "pytest")
_TEST_GATE_PATH = ".github/workflows/test.yml"
_MANUAL_RUN_PATH = ".github/workflows/run-atlas.yml"

_RELEASE_METADATA_PATHS = (
    "VERSION",
    "pyproject.toml",
    "MANIFEST.json",
)
_SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")


def produce_repo_review(
    task: str,
    plan: AtlasPlan,
    evidence_base: EvidenceBase,
) -> str:
    """Return one deterministic repo-review result, or nothing.

    Producers are deliberately narrow. They may only emit findings that can be
    tied directly to Observation.v1 provenance and re-checked by the evaluator.
    If a producer cannot identify one unambiguous fact pattern, it returns an
    empty string rather than guessing.
    """
    review = plan.review
    if plan.route_name != "repo_review" or review is None:
        return ""

    for producer in _PRODUCERS:
        output = producer(task, plan, evidence_base)
        if output:
            return output
    return ""


def _produce_ci_test_command_parity(
    task: str,
    plan: AtlasPlan,
    evidence_base: EvidenceBase,
) -> str:
    review = plan.review
    if review is None or review.topic != "ci" or not _asks_test_command_parity(task):
        return ""

    by_path = {observation.path: observation for observation in evidence_base.observations}
    gate = by_path.get(_TEST_GATE_PATH)
    manual = by_path.get(_MANUAL_RUN_PATH)
    if gate is None or manual is None:
        return ""

    gate_command = _single_test_command(gate)
    manual_command = _single_test_command(manual)
    if gate_command is None or manual_command is None:
        return ""

    gate_text, gate_line, gate_quote = gate_command
    manual_text, manual_line, manual_quote = manual_command
    findings = [
        _contains_finding(
            gate,
            gate_text,
            gate_line,
            gate_quote,
            limitation=(
                "This establishes the literal command in the ordinary test gate; "
                "it does not establish surrounding runner/environment parity."
            ),
        ),
        _contains_finding(
            manual,
            manual_text,
            manual_line,
            manual_quote,
            limitation=(
                "This establishes the literal command in the manual workflow; "
                "it does not establish surrounding runner/environment parity."
            ),
        ),
    ]

    same = gate_text == manual_text
    relation = "samma" if same else "olika"
    conclusion = (
        f"De två observerade workflow-filerna använder {relation} normaliserade "
        f"testkommandon. Ordinarie gate: `{gate_text}`. Manuell körning: "
        f"`{manual_text}`."
    )
    return _render(
        heading="CI test-command parity",
        conclusion=conclusion,
        findings=findings,
    )


def _produce_release_changelog_parity(
    task: str,
    plan: AtlasPlan,
    evidence_base: EvidenceBase,
) -> str:
    review = plan.review
    if (
        review is None
        or review.topic != "release_changelog"
        or not _asks_release_changelog_parity(task)
    ):
        return ""

    by_path = {
        observation.path: observation
        for observation in evidence_base.observations
    }
    pyproject = by_path.get("pyproject.toml")
    changelog = by_path.get("CHANGELOG.md")
    if pyproject is None or changelog is None:
        return ""

    package = _pyproject_version(pyproject)
    release = _changelog_version(changelog)
    if package is None or release is None:
        return ""

    package_version, package_line, package_quote, package_literal = package
    release_version, release_line, release_quote, release_literal = release
    findings = [
        _contains_finding(
            pyproject,
            package_literal,
            package_line,
            package_quote,
            limitation=(
                "This establishes the package version declared in [project]."
            ),
        ),
        _contains_finding(
            changelog,
            release_literal,
            release_line,
            release_quote,
            limitation=(
                "This establishes the first semver release heading visible in "
                "the bounded CHANGELOG window selected by the loop."
            ),
        ),
    ]

    relation = "matchar" if package_version == release_version else "matchar inte"
    conclusion = (
        f"CHANGELOG-versionen `{release_version}` {relation} package-versionen "
        f"`{package_version}` i pyproject.toml."
    )
    return _render(
        heading="Changelog version parity",
        conclusion=conclusion,
        findings=findings,
    )


def _produce_release_metadata_parity(
    task: str,
    plan: AtlasPlan,
    evidence_base: EvidenceBase,
) -> str:
    review = plan.review
    if review is None or review.topic != "release_metadata" or not _asks_release_metadata_parity(task):
        return ""

    by_path = {observation.path: observation for observation in evidence_base.observations}
    if any(path not in by_path for path in _RELEASE_METADATA_PATHS):
        return ""

    parsed = {
        "VERSION": _version_file(by_path["VERSION"]),
        "pyproject.toml": _pyproject_version(by_path["pyproject.toml"]),
        "MANIFEST.json": _manifest_version(by_path["MANIFEST.json"]),
    }
    if any(item is None for item in parsed.values()):
        return ""

    values = {
        path: item[0]
        for path, item in parsed.items()
        if item is not None
    }
    findings = []
    for path in _RELEASE_METADATA_PATHS:
        version, line_number, quote, literal = parsed[path]  # type: ignore[misc]
        findings.append(
            _contains_finding(
                by_path[path],
                literal,
                line_number,
                quote,
                limitation=(
                    "This establishes only the version literal in this observed "
                    "source; cross-source agreement is computed deterministically."
                ),
            )
        )

    unique = sorted(set(values.values()))
    if len(unique) == 1:
        conclusion = (
            "De tre observerade package-metadata-källorna anger samma version: "
            f"`{unique[0]}`."
        )
    else:
        rendered = ", ".join(f"{path}={version}" for path, version in values.items())
        conclusion = f"De observerade package-versionerna skiljer sig: {rendered}."

    return _render(
        heading="Package version metadata parity",
        conclusion=conclusion,
        findings=findings,
    )


def _render(
    *,
    heading: str,
    conclusion: str,
    findings: list[dict[str, object]],
) -> str:
    bullets = "\n".join(f"- {finding['claim']}" for finding in findings)
    block = json.dumps(findings, ensure_ascii=False, indent=2)
    return (
        f"\n## {heading}\n"
        + conclusion
        + "\n\n## Findings\n"
        + bullets
        + "\n\n```"
        + FINDINGS_FENCE
        + "\n"
        + block
        + "\n```\n"
    )


def _asks_test_command_parity(task: str) -> bool:
    text = task.lower()
    asks_test_command = "testkommando" in text or "test command" in text
    asks_same = "samma" in text or "same" in text
    return asks_test_command and asks_same


def _asks_release_changelog_parity(task: str) -> bool:
    text = task.lower()
    names_changelog = "changelog" in text
    asks_agreement = any(
        marker in text
        for marker in ("match", "samma", "synk", "sync", "överens", "agree")
    )
    return names_changelog and asks_agreement


def _asks_release_metadata_parity(task: str) -> bool:
    text = task.lower()
    names_metadata_source = any(
        marker in text
        for marker in ("manifest.json", "pyproject.toml", "version metadata", "versionsmetadata")
    )
    asks_agreement = any(
        marker in text
        for marker in ("samma", "synk", "sync", "överens", "agree", "match")
    )
    return names_metadata_source and asks_agreement


def _single_test_command(
    observation: Observation,
) -> tuple[str, int, str] | None:
    candidates: list[tuple[str, int, str]] = []
    for offset, line in enumerate(observation.excerpt.splitlines()):
        stripped = line.strip()
        if stripped.startswith("- run:"):
            command = stripped[len("- run:"):].strip()
        elif stripped.startswith("run:"):
            command = stripped[len("run:"):].strip()
        else:
            continue
        if command and any(marker in command for marker in _TEST_COMMAND_MARKERS):
            candidates.append((command, observation.line_start + offset, line))

    return candidates[0] if len(candidates) == 1 else None


def _version_file(
    observation: Observation,
) -> tuple[str, int, str, str] | None:
    candidates = []
    for offset, line in enumerate(observation.excerpt.splitlines()):
        value = line.strip()
        if value and _SEMVER.fullmatch(value):
            candidates.append(
                (value, observation.line_start + offset, line, value)
            )
    return candidates[0] if len(candidates) == 1 else None


def _pyproject_version(
    observation: Observation,
) -> tuple[str, int, str, str] | None:
    section = ""
    candidates: list[tuple[str, int, str, str]] = []
    for offset, line in enumerate(observation.excerpt.splitlines()):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped
            continue
        if section != "[project]":
            continue
        match = re.fullmatch(r'version\s*=\s*"([^"]+)"', stripped)
        if match:
            version = match.group(1)
            if _SEMVER.fullmatch(version):
                candidates.append(
                    (
                        version,
                        observation.line_start + offset,
                        line,
                        stripped,
                    )
                )
    return candidates[0] if len(candidates) == 1 else None


def _changelog_version(
    observation: Observation,
) -> tuple[str, int, str, str] | None:
    for offset, line in enumerate(observation.excerpt.splitlines()):
        stripped = line.strip()
        match = re.match(r"^##\s+v([^\s]+)", stripped)
        if not match:
            continue
        version = match.group(1)
        if _SEMVER.fullmatch(version):
            return (
                version,
                observation.line_start + offset,
                line,
                f"## v{version}",
            )
    return None


def _manifest_version(
    observation: Observation,
) -> tuple[str, int, str, str] | None:
    candidates: list[tuple[str, int, str, str]] = []
    for offset, line in enumerate(observation.excerpt.splitlines()):
        match = re.search(r'"version"\s*:\s*"([^"]+)"', line)
        if match:
            version = match.group(1)
            if _SEMVER.fullmatch(version):
                candidates.append(
                    (
                        version,
                        observation.line_start + offset,
                        line,
                        match.group(0),
                    )
                )
    return candidates[0] if len(candidates) == 1 else None


def _contains_finding(
    observation: Observation,
    text: str,
    line_number: int,
    quoted_line: str,
    *,
    limitation: str,
) -> dict[str, object]:
    typed = TypedClaim(
        kind=ClaimKind.CONTAINS,
        source_id=observation.source_id,
        text=text,
    )
    return {
        "claim": typed.render(
            observation.path,
            observation.line_start,
            observation.line_end,
        ),
        "scope": observation.path,
        "severity": "unknown",
        "severity_rationale": (
            "Deterministic repository fact; no defect severity is assigned."
        ),
        "evidence": [
            {
                "source_id": observation.source_id,
                "content_sha256": observation.content_sha256,
                "line_start": line_number,
                "line_end": line_number,
                "quoted": quoted_line,
            }
        ],
        "typed_claim": {
            "kind": typed.kind.value,
            "source_id": typed.source_id,
            "text": typed.text,
        },
        "limitations": [limitation],
        "reproducible_command": "unknown",
    }


_PRODUCERS: tuple[Producer, ...] = (
    _produce_ci_test_command_parity,
    _produce_release_changelog_parity,
    _produce_release_metadata_parity,
)


__all__ = ["produce_repo_review"]
