# GitHub Actions

Atlas Core includes a manual GitHub Actions runner:

```text
.github/workflows/run-atlas.yml
```

The workflow can run the Atlas loop against a task and upload the result as an artifact.

## Trigger from GitHub UI

Open:

```text
Actions → Run Atlas Core → Run workflow
```

Set:

```text
task:        granska atlas-core och hitta nästa bästa förbättring
json_output: false
repo_target: optional, for example MCamner/mqobsidian
```

## Trigger from GitHub CLI

```bash
gh workflow run "Run Atlas Core" \
  --field task="granska atlas-core och hitta nästa bästa förbättring" \
  --field json_output="false"
```

With a repo target:

```bash
gh workflow run "Run Atlas Core" \
  --field task="granska MCamner/mqobsidian och hitta P0/P1/P2 förbättringar" \
  --field repo_target="MCamner/mqobsidian" \
  --field json_output="false"
```

## View runs

```bash
gh run list --workflow="run-atlas.yml" --limit 5
```

## View logs

```bash
gh run view <RUN_ID> --log
```

## Download result artifact

```bash
RUN_ID=$(gh run list \
  --workflow="run-atlas.yml" \
  --json databaseId,conclusion \
  --jq '[.[] | select(.conclusion=="success")][0].databaseId')

gh run download "$RUN_ID" -n atlas-result -D atlas-runs
cat atlas-runs/atlas-result.md
```

## What the workflow does

1. Checks out `atlas-core`
2. Installs Python 3.11
3. Installs Atlas Core
4. Installs pytest
5. Runs tests
6. Runs `atlas run`
7. Uploads `atlas-result`

## Notes

The workflow is manual by design. Atlas Core should not automatically act on repo state until write boundaries and approval rules are mature.
