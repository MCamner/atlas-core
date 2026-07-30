# GitHub Reader Adapter

Atlas Core v0.2 adds a small GitHub reader adapter.

It can observe a public GitHub repository before running the loop:

```bash
atlas run "granska MCamner/mqobsidian och hitta P0/P1/P2" --repo MCamner/mqobsidian
```

For private repos or higher API limits, set:

```bash
export GITHUB_TOKEN="..."
```

The adapter intentionally reads a small surface first:

- README.md
- pyproject.toml
- package.json
- key docs
- GitHub Actions workflows

It does not broad-scan the full repository by default.
