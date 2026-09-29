from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path

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

_PARITY_GATE_PATH = "release-check.sh"
_PARITY_POLICY_PATH = "scripts/check-gate-parity.py"
_SETUP_PREFIXES = (
    "uv pip install",
    "uv sync",
    "uv build",
    "uv venv",
    "pip install",
)
_WRAPPERS = ("uv", "run", "bash", "sh", "python", "python3", "./")


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


def _produce_ci_release_gate_parity(
    task: str,
    plan: AtlasPlan,
    evidence_base: EvidenceBase,
) -> str:
    review = plan.review
    if review is None or review.topic != "ci_gate_parity":
        return ""

    by_path = {observation.path: observation for observation in evidence_base.observations}
    gate = by_path.get(_PARITY_GATE_PATH)
    policy = by_path.get(_PARITY_POLICY_PATH)
    if gate is None or policy is None or gate.read_in_full() is not True:
        return ""

    workflow_scope = _workflow_scope(policy)
    exceptions = _parity_exceptions(policy)
    if workflow_scope is None or exceptions is None:
        return ""

    in_scope: dict[str, Observation] = {}
    for name, enabled in workflow_scope.items():
        if not enabled:
            continue
        observation = by_path.get(f".github/workflows/{name}")
        if observation is None or observation.read_in_full() is not True:
            return ""
        in_scope[name] = observation

    local = _local_gate_checks(gate)
    if not local:
        return ""

    ci: dict[str, str] = {}
    for observation in in_scope.values():
        for key, command in _workflow_checks(observation, local).items():
            ci.setdefault(key, command)

    drift: list[str] = []
    for key in sorted(set(ci) - set(local)):
        if key not in exceptions:
            drift.append(f"CI-only check: {key}")
    for key in sorted(set(local) - set(ci)):
        if key not in exceptions:
            drift.append(f"local-only check: {key}")
    for key in sorted(set(local) & set(ci)):
        local_targets = _targets(local[key], key)
        ci_targets = _targets(ci[key], key)
        if local_targets != ci_targets:
            drift.append(
                f"target drift for {key}: local={sorted(local_targets)} "
                f"ci={sorted(ci_targets)}"
            )

    findings: list[dict[str, object]] = []
    evidence_markers: list[tuple[Observation, str, str]] = [
        (gate, "check-gate-parity.py",
         "This establishes that the local release gate invokes its parity check."),
        (policy, '"tests.yml": True',
         "This establishes that tests.yml is declared in scope by the observed parity policy."),
        (policy, '"markdownlint.yml": True',
         "This establishes that markdownlint.yml is declared in scope by the observed parity policy."),
        (policy, '"mq-stack-gate.yml": False',
         "This establishes that the cross-repository stack gate is explicitly out of scope for local parity."),
    ]
    tests_workflow = in_scope.get("tests.yml")
    if tests_workflow is not None:
        evidence_markers.extend(
            [
                (tests_workflow, "scripts/check-gate-parity.py",
                 "This establishes that CI invokes the parity checker directly."),
                (tests_workflow, "./release-check.sh",
                 "This establishes that one observed CI job delegates to the local release gate."),
            ]
        )

    for observation, marker, limitation in evidence_markers:
        finding = _finding_for_marker(observation, marker, limitation=limitation)
        if finding is not None:
            findings.append(finding)

    if len(findings) < 3:
        return ""

    enabled_workflows = ", ".join(sorted(in_scope))
    disabled = ", ".join(
        sorted(name for name, is_enabled in workflow_scope.items() if not is_enabled)
    ) or "none"
    declared_exceptions = ", ".join(sorted(exceptions)) or "none"
    if drift:
        conclusion = (
            "Den deterministiska gate-jämförelsen hittar odeklarerad drift: "
            + "; ".join(drift)
            + f". In-scope workflows: {enabled_workflows}. Out-of-scope: {disabled}. "
            + f"Explicit exceptions: {declared_exceptions}."
        )
    else:
        conclusion = (
            "Den deterministiska gate-jämförelsen hittar ingen odeklarerad drift "
            f"mellan {_PARITY_GATE_PATH} och observerade in-scope workflows "
            f"({enabled_workflows}). Out-of-scope: {disabled}. Explicit exceptions: "
            f"{declared_exceptions}. Detta jämför deklarerade checks och targets; "
            "det säger inte att checks faktiskt passerar i CI."
        )
    return _render(
        heading="CI/release gate parity",
        conclusion=conclusion,
        findings=findings,
    )


def _workflow_scope(observation: Observation) -> dict[str, bool] | None:
    scope: dict[str, bool] = {}
    in_scope = False
    for line in observation.excerpt.splitlines():
        stripped = line.strip()
        if stripped.startswith("WORKFLOW_SCOPE"):
            in_scope = True
            continue
        if in_scope and stripped == "}":
            break
        if not in_scope:
            continue
        match = re.match(r'^"([^"]+\.yml)"\s*:\s*(True|False)\b', stripped)
        if match:
            scope[match.group(1)] = match.group(2) == "True"
    return scope or None


def _parity_exceptions(observation: Observation) -> set[str] | None:
    exceptions: set[str] = set()
    in_exceptions = False
    for line in observation.excerpt.splitlines():
        stripped = line.strip()
        if stripped.startswith("EXCEPTIONS"):
            in_exceptions = True
            continue
        if in_exceptions and stripped == "}":
            break
        if not in_exceptions:
            continue
        match = re.match(r'^"([^"]+)"\s*:', stripped)
        if match:
            exceptions.add(match.group(1))
    return exceptions


def _local_gate_checks(observation: Observation) -> dict[str, str]:
    found: dict[str, str] = {}
    for raw in observation.excerpt.splitlines():
        line = raw.strip()
        if not line.startswith("run_check "):
            continue
        rest = line[len("run_check "):]
        if rest.startswith('"'):
            try:
                end = rest.index('"', 1)
            except ValueError:
                continue
            command = rest[end + 1:]
        else:
            command = rest.split(maxsplit=1)[1] if " " in rest else ""
        key = _check_key(command.replace('"$ROOT"/', "").replace("$ROOT/", ""))
        if key:
            found[key] = command.strip()
    return found


def _workflow_checks(
    observation: Observation,
    local: dict[str, str],
) -> dict[str, str]:
    found: dict[str, str] = {}
    for raw in observation.excerpt.splitlines():
        stripped = raw.strip()
        uses_match = re.match(r"^-?\s*uses:\s*(\S+)", stripped)
        if uses_match:
            uses = uses_match.group(1)
            if "checkout" not in uses and "setup-uv" not in uses:
                key = uses.split("@")[0].split("/")[-1]
                found.setdefault(key, uses)
            continue

        run_match = re.match(r"^-?\s*run:\s*(.+)$", stripped)
        if not run_match:
            continue
        command = run_match.group(1).strip()
        if command in {"|", ">"}:
            continue
        key = _check_key(command)
        if not key:
            continue
        if key == "release-check.sh":
            for gate_key, gate_command in local.items():
                found.setdefault(gate_key, gate_command)
            continue
        found.setdefault(key, command)
    return found


def _check_key(command: str) -> str | None:
    command = command.strip().replace('"', "")
    if not command or command.startswith("#"):
        return None
    if any(command.startswith(prefix) for prefix in _SETUP_PREFIXES):
        return None

    tokens = command.split()
    while tokens:
        head = tokens[0]
        if head == "--extra":
            if len(tokens) < 2:
                return None
            del tokens[:2]
            continue
        if head.startswith("-") or head in _WRAPPERS:
            tokens.pop(0)
            continue
        break
    if not tokens:
        return None

    name = tokens[0].lstrip("./").replace("$ROOT/", "")
    return Path(name).name or None


def _targets(command: str, key: str) -> set[str]:
    tokens = [token.replace('"', "").replace("$ROOT/", "") for token in command.split()]
    start = 0
    for index, token in enumerate(tokens):
        if Path(token).name == key:
            start = index + 1
            break
    return {
        token.lstrip("./").rstrip("/")
        for token in tokens[start:]
        if "/" in token and not token.startswith("-")
    }


def _finding_for_marker(
    observation: Observation,
    marker: str,
    *,
    limitation: str,
) -> dict[str, object] | None:
    for offset, line in enumerate(observation.excerpt.splitlines()):
        if marker not in line:
            continue
        return _contains_finding(
            observation,
            marker,
            observation.line_start + offset,
            line,
            limitation=limitation,
        )
    return None


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
    _produce_ci_release_gate_parity,
    _produce_ci_test_command_parity,
    _produce_release_changelog_parity,
    _produce_release_metadata_parity,
)


__all__ = ["produce_repo_review"]
