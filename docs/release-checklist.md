# Release Checklist

This checklist describes a release gate; checking it does not itself publish a
release. Follow it from a clean checkout of the intended release commit.

## Before tagging

- [ ] Confirm `git status --porcelain` is empty and the branch is the reviewed
  release commit, not a local-only worktree state.
- [ ] Run `python -m unittest discover -s tests`.
- [ ] Run `mypy atlas_core tests scripts/pinned_repo_review.py` and
  `pyright atlas_core tests scripts/pinned_repo_review.py` using the same
  versions required by CI.
- [ ] Run the schema/contract/migration tests in the full suite; check that
  every changed schema has an intentional identifier/version and a migration
  or a documented reason no migration is needed.
- [ ] Run the opt-in MQ contract tests only when all three repository paths are
  explicitly configured; record skips as skips, not passes.
- [ ] Review `CHANGELOG.md`, `VERSION`, `MANIFEST.json`, `pyproject.toml` and
  `atlas_core.__version__` together. `tests/test_release_metadata.py` enforces
  equality and changelog ordering.
- [ ] Review the generated wheel and sdist contents. Build twice from clean
  checkouts with identical pinned build inputs and `SOURCE_DATE_EPOCH`; compare
  SHA-256 digests. A mismatch blocks release until explained and fixed.
- [ ] Generate and inspect the release SBOM; verify it describes the same
  source/version as the wheel. The test workflow now uploads a CycloneDX 1.5
  runtime-dependency SBOM from `uv.lock`; the release artifact still needs its
  own matching SBOM attached and digest-verified.
- [ ] Confirm required CI, dependency and secret-scanning checks are green and
  the independent security review is recorded. The configured workflow
  provides dependency and secret-scanning gates; verify they are required by
  the release-branch rules. See [security review](security-review.md).
- [ ] Read the support matrix and publish only the Python/OS/provider cells
  with matching test evidence.

## Publish and recover

- [ ] Create an annotated `vX.Y.Z` tag only after the checks above pass; never
  move or force-update a published tag.
- [ ] Attach the wheel, sdist, SBOM and release notes to the same tag. Verify
  artifact digests after upload.
- [ ] Smoke-test installation from the built wheel in a clean environment and
  run the documented read-only example. Do not send a live provider request
  unless that smoke test was separately opted into and configured.
- [ ] If an artifact is wrong, stop distribution, mark the release withdrawn,
  and publish a corrected higher patch version. Do not rewrite the tag or
  delete consumer data. Follow [the operations runbook](operations-runbook.md)
  for recovery and incident notes.

## Reproducibility status

The project now pins GitHub Actions, CI tooling and PEP 517 build-system
versions. CI dependencies are hash-locked through `uv.lock`, and CI produces a
validated CycloneDX runtime-dependency SBOM. PEP 517 build-system versions are
pinned in `pyproject.toml`, but their distributions are not hash-locked in
`uv.lock`.

The remaining release blockers are reproducible double-build verification,
artifact-level integrity for build-system inputs, and a release SBOM tied to
the actual wheel and sdist.
