# Release Integrity

Code security baseline: `6474f17d4ca6fa75d56f29d2475ad4bfcb1c7d60`

## Mechanism

`scripts/reproducible_build.py`, run in the `test` workflow:

- requires a clean checkout and builds in two detached worktrees at the same
  commit
- derives `SOURCE_DATE_EPOCH` from the commit timestamp
- builds with the hash-locked `build` dependency group, without unpinned build
  isolation, and checks that group against `pyproject.toml`'s PEP 517
  requirements
- canonicalizes sdist container metadata only (tar/gzip timestamps,
  owner/group, PAX time entries); member contents are not rewritten
- fails unless filenames, package/version metadata and both SHA-256 digests
  match across the two builds
- writes a CycloneDX 1.5 release SBOM and `release-integrity.json`

A separate step exports a CycloneDX 1.5 runtime SBOM (`atlas-core.cdx.json`).

## Artifact for the code baseline

- Run: [36297845486](https://github.com/MCamner/atlas-core/actions/runs/36297845486)
- Artifact: `atlas-core-release-integrity`, expires 2026-12-26T05:39:49Z
- `source_commit` in manifest: `6474f17d4ca6fa75d56f29d2475ad4bfcb1c7d60`
- `SOURCE_DATE_EPOCH`: `1790487585` (equals the commit timestamp)

| File | SHA-256 | Size |
| --- | --- | ---: |
| `atlas_core-1.0.0-py3-none-any.whl` | `1a4b4fbddb08075c9823d2b64693da6d869f30833ff0bcd1ead7bc00f72078ad` | 207065 bytes |
| `atlas_core-1.0.0.tar.gz` | `8b5a1904eeb5728852236976a8ca10174761c5ffa978cdd1b7d655fab2ada191` | 353965 bytes |
| `atlas-core-1.0.0.cdx.json` | `c536741de62835d512cf06e5d2c6cb1976de01c84d80f5453a17ef2505eb9b92` | 1233 bytes |
| `release-integrity.json` | `c0f76b49506b4574f56991f887ea4c86ff0bc5302d0e9b9c71474aa40403ba69` | 722 bytes |

The authors downloaded the artifact and computed these digests from the bytes.
The manifest's wheel, sdist and SBOM digests match.

`SOURCE_DATE_EPOCH` comes from the commit timestamp, so a later commit
produces different digests even when no packaged file changed (observed
between `217c113` and `07ac394`). Reproducibility is claimed per commit. For
a release, the artifact from the tagged commit is the one to attach.

## Not done

- No GitHub release exists. The only tag is `v0.2.0`. The verified
  distributions, SBOM and manifest have not been attached to a release tag,
  and the artifact expires on the date above unless retained.
- Artifacts are not signed and have no provenance attestation.
