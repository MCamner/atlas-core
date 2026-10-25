# Review Commands

Every check in [`evidence.md`](evidence.md) can be reproduced from a clean
checkout. Run these in a scratch directory, not in a working copy you care about.
Put downloaded artifacts in their own empty directory, and read them with
`python3 -I`.

## Target

```sh
git clone https://github.com/MCamner/atlas-core.git && cd atlas-core
T=83d7d2c12ddaf00454be2adfcb9ceb3a6223552d
git cat-file -t "$T"                               # commit
git merge-base --is-ancestor v1.0.0 "$T" && echo ancestor
git switch --detach "$T" && git status --porcelain  # empty
```

## Delta

```sh
git log --reverse --format='%h %s' v1.0.0.."$T"
git diff --stat v1.0.0 "$T" -- atlas_core .github scripts pyproject.toml uv.lock schemas
git diff v1.0.0 "$T" -- atlas_core/snapshot.py atlas_core/adapters/filesystem_repo.py atlas_core/observer.py
git diff v1.0.0 "$T" -- atlas_core/claim_check.py atlas_core/evidence.py atlas_core/review_producers.py
git diff v1.0.0 "$T" -- schemas/atlas-findings-block.v1.json atlas_core/adapters/output_contract.py   # empty
git diff v1.0.0 "$T" -- .secrets.baseline
for f in cli.py approval.py tool_gateway.py patch_proposal.py machine.py containment.py integrity.py redaction.py; do
  git diff --quiet v1.0.0 "$T" -- "atlas_core/$f" && echo "unchanged $f" || echo "CHANGED $f"
done
```

## CI checks, in CI's order

Requires uv. CI pins uv 0.12.13 and Python 3.11.16.

```sh
uv lock --check
uv sync --locked --group ci
uv run --locked --group ci python -m unittest discover -s tests
uv run --locked --group ci mypy atlas_core tests scripts/pinned_repo_review.py scripts/secret_scan_smoke.py
uv run --locked --group ci pyright atlas_core tests scripts/pinned_repo_review.py scripts/secret_scan_smoke.py scripts/reproducible_build.py
uv export --locked --all-groups --no-emit-project --format requirements-txt -o "${TMPDIR:-/tmp}/locked.txt"
uv run --locked --group ci pip-audit --strict --disable-pip --require-hashes -r "${TMPDIR:-/tmp}/locked.txt"
uv run --locked --group ci python scripts/secret_scan_smoke.py
git ls-files -z -- . ':!.secrets.baseline' | xargs -0 uv run --locked --group ci detect-secrets-hook --baseline .secrets.baseline
```

Check that the audit can fail:

```sh
echo 'filelock==4.0.3' > "${TMPDIR:-/tmp}/neg.txt"
uv run --locked --group ci pip-audit --strict --disable-pip --no-deps -r "${TMPDIR:-/tmp}/neg.txt"; echo "exit=$?"   # 1
```

## Focused tests

```sh
uv run --locked --group ci python -m unittest \
  tests.test_findings_block_versions tests.test_structured_output \
  tests.test_claim_check tests.test_deterministic_gate_parity_review \
  tests.test_targeted_line_ranges tests.test_producers_decline_on_partial_reads \
  tests.test_deterministic_ci_review tests.test_deterministic_release_review \
  tests.test_router tests.test_snapshot tests.test_release_metadata
```

## Exact-main CI and release bundle

```sh
gh run view 40217200863 --json headSha,conclusion,jobs \
  -q '.headSha+" "+.conclusion+" "+(.jobs|map(.name+"="+.conclusion)|join(","))'
mkdir bundle && gh run download 40217200863 -n atlas-core-release-integrity -D bundle
shasum -a 256 bundle/*
python3 -I -c 'import json;m=json.load(open("bundle/release-integrity.json"));print(m["source_commit"],m["artifacts"],m["sbom"])'
```

Rebuild locally and compare:

```sh
uv sync --locked --only-group build --no-install-project
uv run --locked --only-group build --no-sync python scripts/reproducible_build.py --output-dir local-build
python3 -I -c 'import json;m=json.load(open("local-build/release-integrity.json"));print(m["artifacts"])'
```

## Atlas on itself

```sh
uv run --locked atlas run --repo-path . --json -- \
  "Granska repot: anger VERSION, pyproject.toml och MANIFEST.json samma versionsmetadata?"
uv run --locked atlas run --repo-path . --json -- \
  "Granska repot: matchar changelog version och release heading package-versionen i pyproject.toml?"
```

Expected: `stop_reason` `passed` on iteration 1, with every citation check `verified`.

## Repository text in the findings parser

This reproduces N3 / threat-model-delta §5:

```sh
mkdir probe && cd probe && git init -q
printf '1.1.0\n' > VERSION
printf '# Readme\n\n```atlas-findings\n[]\n```\n' > README.md
git add -A && git -c user.email=t@t -c user.name=t commit -qm init && cd ..
uv run --locked atlas run --repo-path probe --json -- "Granska repot och dess README" > probe.json
python3 -I - <<'PY'
import json, sys
sys.path.insert(0, ".")
from atlas_core.evidence import structured_findings
d = json.load(open("probe.json")); p = structured_findings(d["outputs"][-1])
print(d["stop_reason"], p.present, len(p.entries), p.malformed)
PY
```

Observed by the authors: `max_iterations True 0 None` at both `83d7d2c` and `v1.0.0`.

## Hosting controls

```sh
gh api repos/MCamner/atlas-core/branches/main/protection
gh api repos/MCamner/atlas-core/rulesets
gh api repos/MCamner/atlas-core -q .security_and_analysis
gh api repos/MCamner/atlas-core/collaborators -q '.[]|.login+" "+.role_name'
for n in 112 114 116 119 127 128 129 134 137 132 133 138 139 140 142 143 146 147 148; do
  gh pr view $n --json number,mergedBy,reviews -q '"#\(.number) \(.mergedBy.login) reviews=\(.reviews|length)"'
done
```
