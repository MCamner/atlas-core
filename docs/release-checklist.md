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
- [ ] Review the generated wheel and sdist contents. The test workflow builds
  both from two clean detached worktrees with the same commit-derived
  `SOURCE_DATE_EPOCH`, using the hash-locked `build` dependency group. Sdist tar
  owner/time/gzip metadata is canonicalized to that epoch; member contents are
  unchanged. It fails closed unless both final SHA-256 digests match and package
  metadata agrees. Review `release-integrity.json` and retain the wheel and sdist
  digests.
- [ ] Generate and inspect the release SBOM; verify its package/version match
  the wheel and sdist. The test workflow writes source commit and both artifact
  hashes into the CycloneDX 1.5 SBOM and records its SHA-256 in
  `release-integrity.json`. Verify all files are present in the uploaded
  `atlas-core-release-integrity` artifact.
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

The project pins GitHub Actions and CI tooling. PEP 517 build-system inputs are
exact-version-pinned in `pyproject.toml` and repeated in the `build` dependency
group, whose distribution hashes are recorded in `uv.lock`. The test workflow
builds wheel and sdist twice from clean worktrees. It canonicalizes only sdist
archive metadata (timestamps, owner/group fields, PAX time entries and gzip
header) to the commit-derived `SOURCE_DATE_EPOCH`; file payloads are never
rewritten. It fails closed on final artifact digest mismatch, validates a
release SBOM against package/version metadata, and records the source commit
plus wheel, sdist and SBOM digests in `release-integrity.json`.

This CI evidence does not publish a release. A release must attach the verified
wheel, sdist, SBOM and digest manifest to the same tag and retain their artifact
digests.
