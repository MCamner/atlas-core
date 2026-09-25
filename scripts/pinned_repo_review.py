"""P1.1 box five: the composed loop against a pinned public repository.

Read-only, and reproducible:

    git clone https://github.com/MCamner/mq-image-analyze /tmp/mq-image-analyze
    git -C /tmp/mq-image-analyze checkout e5c4064733c4fced62b71f47e7b16e9335168532
    python3 scripts/pinned_repo_review.py /tmp/mq-image-analyze

Nothing is written to the repository under review. The findings are the
operator's, written as typed claims: Atlas Core ships no model, so what is
measured is whether the loop establishes or refuses them. See
`docs/pinned-repo-review.md` for the result and its limits.
"""
from __future__ import annotations

import json
import subprocess
import sys
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from atlas_core import AtlasController
from atlas_core.adapters.model import ModelResult
from atlas_core.budget import RunBudget, RunLimits
from atlas_core.claim_check import ClaimKind, TypedClaim
from atlas_core.evidence import FINDINGS_FENCE
from atlas_core.evidence_base import EvidenceBase
from atlas_core.observation import Observation
from atlas_core.observer import ObservationRequest
from atlas_core.snapshot import collect_observation, take_snapshot

PINNED_COMMIT = "e5c4064733c4fced62b71f47e7b16e9335168532"

if len(sys.argv) != 2:
    raise SystemExit("usage: pinned_repo_review.py <path-to-checkout>")
ROOT = Path(sys.argv[1]).resolve()
TASK = "granska repot mq-image-analyze: lokal och CI gate-paritet"
LIMITS = RunLimits(
    wall_seconds=60, model_calls=6, tool_calls=20, tokens=500, output_bytes=2_000_000
)

TRACKED = subprocess.run(
    ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
).stdout.split()

snapshot = take_snapshot(ROOT)
if snapshot.commit != PINNED_COMMIT:
    raise SystemExit(
        f"checkout is at {snapshot.commit}, not the pinned {PINNED_COMMIT}"
    )


class Host:
    """Lists the directory and reads. Core does neither."""

    def __init__(self) -> None:
        self.rounds: list[list[str]] = []

    def observe(
        self, request: ObservationRequest, *, budget: RunBudget
    ) -> list[Observation]:
        paths = sorted(
            {p for p in TRACKED for q in request.patterns if fnmatch(p, q)}
        )
        self.rounds.append(paths)
        observations = []
        for path in paths:
            budget.check()
            budget.reserve_tool()
            observations.append(collect_observation(snapshot, path))
            budget.check()
        return observations


def finding(
    obs: Observation, kind: ClaimKind, text: str, severity: str, why: str
) -> dict[str, Any]:
    typed = TypedClaim(kind=kind, source_id=obs.source_id, text=text)
    lines = obs.excerpt.splitlines()
    if kind is ClaimKind.CONTAINS:
        index = next(i for i, line in enumerate(lines) if text in line)
        span = (obs.line_start + index, obs.line_start + index)
        quoted = lines[index]
    else:
        span = (obs.line_start, obs.line_end)
        quoted = obs.excerpt
    return {
        "claim": typed.render(obs.path, obs.line_start, obs.line_end),
        "scope": obs.path,
        "severity": severity,
        "severity_rationale": why,
        "evidence": [
            {
                "source_id": obs.source_id,
                "content_sha256": obs.content_sha256,
                "line_start": span[0],
                "line_end": span[1],
                "quoted": quoted,
            }
        ],
        "typed_claim": {
            "kind": typed.kind.value,
            "source_id": typed.source_id,
            "text": typed.text,
        },
    }


def output(findings: list[dict[str, Any]], observed: list[str]) -> str:
    body = (
        "# Granskning av CI-workflow och release-gate\n\n"
        "Granskningen nedan bygger på de källor som lästes denna körning, vid "
        "den pinnade commiten, och prövar vad CI-konfigurationen deklarerar "
        "att den kör.\n\n"
        "## Observed sources\n"
        + "\n".join(f"- `{p}`" for p in observed)
        + "\n\n## Findings\n"
        + "\n".join(f"- {f['claim']}" for f in findings)
        + "\n\n## Recommendation\n"
        "Behåll `./release-check.sh --json` som CI-steg; det är det som gör "
        "pariteten strukturell i stället för deklarerad.\n\n"
        "## Next step\n"
        "Läs `release-check.sh` för att pröva den lokala sidan.\n\n"
        "## Confidence\n"
        "Hög för det som lästes; ingen för det som inte lästes.\n"
    )
    if not findings:
        return body
    return body + "\n```" + FINDINGS_FENCE + "\n" + json.dumps(findings) + "\n```\n"


CLAIMS = [
    (
        ".github/workflows/gate-parity.yml",
        ClaimKind.CONTAINS,
        "./release-check.sh --json",
        "P2",
        "Det är detta steg som gör att hela den lokala grinden körs i CI.",
    ),
    (
        ".github/workflows/gate-parity.yml",
        ClaimKind.CONTAINS,
        "--self-test",
        "P2",
        "Ett CI-steg utan lokal motsvarighet; asymmetrin är värd att veta om.",
    ),
    (
        ".github/workflows/tests.yml",
        ClaimKind.CONTAINS,
        "pytest tests/ -v --tb=short",
        "P2",
        "CI:s testkommando, att jämföra med den lokala grindens.",
    ),
    (
        ".github/workflows/markdownlint.yml",
        ClaimKind.CONTAINS,
        'globs: "**/*.md"',
        "P2",
        "CI deklarerar lintens omfång explicit i stället för via konfigfilen.",
    ),
]


def main() -> None:
    host = Host()
    observations = {
        path: collect_observation(snapshot, path)
        for path, *_ in CLAIMS
    }
    findings = [
        finding(observations[path], kind, text, severity, why)
        for path, kind, text, severity, why in CLAIMS
    ]
    resolved = sorted(
        {p for p in TRACKED for q in (".github/workflows/*", "Makefile", "*.yml")
         if fnmatch(p, q)}
    )
    text = output(findings, resolved)

    class Producer:
        def execute(self, **kwargs: Any) -> ModelResult:
            return ModelResult(
                output=text, provider="manual", model="operator",
                metadata={"usage_tokens": "1"},
            )

    run = AtlasController(max_iterations=3, model_adapter=Producer()).run(
        TASK,
        evidence=EvidenceBase(snapshot=snapshot),
        json_mode=True,
        limits=LIMITS,
        observer=host,
    )

    print("commit        :", snapshot.commit)
    print("worktree      :", snapshot.worktree_state)
    print("route         :", run["plan"]["route_name"])
    print("plan topic    :", run["plan"]["review"]["topic"])
    print("plan question :", run["plan"]["review"]["question"])
    print("plan patterns :", run["plan"]["review"]["patterns"])
    print("host rounds   :", host.rounds)
    print("iterations    :", run["iteration"])
    print("stop_reason   :", run["stop_reason"])
    evaluation = run["evaluations"][-1]
    print("passed        :", evaluation["passed"])
    print("unmet         :", evaluation["unmet_criteria"])
    print("\nverdicts:")
    checks = evaluation["citation_checks"]
    for record in checks:
        print(f"  {record['verdict']:22s} {record['severity']:8s} {record['claim'][:96]}")
    ok = (
        run["stop_reason"] == "passed"
        and evaluation["passed"] is True
        and len(checks) == len(CLAIMS)
        and all(record["verdict"] == "verified" for record in checks)
    )
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
