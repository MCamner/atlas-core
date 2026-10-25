# Review Commands

Every check in [`evidence.md`](evidence.md) can be reproduced from a clean
checkout. Run these in a scratch directory, not in a working copy you care about.
Put downloaded artifacts in their own empty directory, and read them with
`python3 -I`.

## Target

```sh
git clone https://github.com/MCamner/atlas-core.git && cd atlas-core
T=7d0d86c3ee88a8b2c62938d36d9fc77ae6fcfd58
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
  tests.test_router tests.test_snapshot tests.test_release_metadata \
  tests.test_findings_trust_boundary
```

## Exact-main CI and release bundle

```sh
gh run view 40243597308 --json headSha,conclusion,jobs \
  -q '.headSha+" "+.conclusion+" "+(.jobs|map(.name+"="+.conclusion)|join(","))'
mkdir bundle && gh run download 40243597308 -n atlas-core-release-integrity -D bundle
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

## SEC-01: repository text is not a finding

The regression suite builds the strongest case, an injected finding with sound
citations, for every git state:

```sh
uv run --locked --group ci python -m unittest tests.test_findings_trust_boundary -v
```

A run-level probe. Build a directory that git cannot describe, with
`docs/install.md` and a `README.md` whose ```` ```atlas-findings ```` block cites
`docs/install.md` with the `source_id` that `atlas_core.observation.derive_source_id`
gives for `sha256(<abs root>\0unknown\0unknown)[:16]`. Then run:

```sh
uv run --locked atlas run --repo-path <dir> --json -- \
  "Granska repots dokumentation: hur installerar man projektet?" > probe.json
python3 -I -c 'import json;d=json.load(open("probe.json"));print(d["stop_reason"],len(d["evaluations"][-1]["citation_checks"]),d["metadata"]["findings_sources"])'
```

The authors observed `max_iterations 0 [... producer_section ...]` at the
target, and `passed` with one verified check before #151. The advisory
GHSA-m8fx-mmrx-c449 holds the full reproduction.

## Hosting controls

```sh
gh api repos/MCamner/atlas-core/branches/main/protection
gh api repos/MCamner/atlas-core/rulesets
gh api repos/MCamner/atlas-core -q .security_and_analysis
gh api repos/MCamner/atlas-core/collaborators -q '.[]|.login+" "+.role_name'
for n in 112 114 116 119 127 128 129 134 137 132 133 138 139 140 142 143 146 147 148 151; do
  gh pr view $n --json number,mergedBy,reviews -q '"#\(.number) \(.mergedBy.login) reviews=\(.reviews|length)"'
done
```
