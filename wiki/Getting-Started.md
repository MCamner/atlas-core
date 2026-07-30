# Getting Started

This page shows the fastest path from clone to a working Atlas Core loop.

## Requirements

- Python 3.11+
- Git
- GitHub CLI if you want to trigger Actions locally

## Install locally

```bash
git clone https://github.com/MCamner/atlas-core.git
cd atlas-core
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

## Run tests

The repo supports the standard unittest runner:

```bash
python -m unittest discover -s tests
```

For pytest-based local checks:

```bash
python -m pip install pytest
python -m pytest -q
```

## Run the loop

```bash
atlas run "granska atlas-core och hitta nästa bästa förbättring"
```

## List routes

```bash
atlas routes
```

## Show version

```bash
atlas version
```

## Run with local repo observations

Use this when Atlas should inspect the current checkout before routing:

```bash
atlas run "granska atlas-core och hitta nästa bästa förbättring" --repo-path .
```

## Run with public GitHub repo observations

Use this when Atlas should read public GitHub repository context:

```bash
atlas run "granska MCamner/mqobsidian och hitta P0/P1/P2 förbättringar" --repo MCamner/mqobsidian
```

## JSON output

```bash
atlas run "bygg målarkitektur för säker AI-assistent" --json
```

## Local memory candidate

```bash
atlas run "förbättra min prompt för repo review" --memory-dir .atlas-memory
```

Atlas memory is optional. The core loop must still run without memory.
