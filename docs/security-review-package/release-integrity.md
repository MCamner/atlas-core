# Release Integrity

Review target: `07ac3944db800b28bfc41fcd933cd10d6b04c00d`

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

## Artifact for the review target

- Run: [36292102442](https://github.com/MCamner/atlas-core/actions/runs/36292102442)
- Artifact: `atlas-core-release-integrity`, expires 2026-12-26T03:40:41Z
- `source_commit` in manifest: `07ac3944db800b28bfc41fcd933cd10d6b04c00d`
- `SOURCE_DATE_EPOCH`: `1790480438` (equals the commit timestamp)

| File | SHA-256 | Size |
| --- | --- | ---: |
| `atlas_core-1.0.0-py3-none-any.whl` | `af8e28576e50e77bf904457dc93d19390e1e1c4dbe574df482ceb1f0498a2d38` | 205083 bytes |
| `atlas_core-1.0.0.tar.gz` | `20e42b4f7ca1749d24d38a8ba1e09f4f9fbca180e834455049195bafd31bc8d5` | 349791 bytes |
| `atlas-core-1.0.0.cdx.json` | `0d73481b1a18955435283597b2cab60a98eadcf88ca72a1504f12980c03af29c` | 1233 bytes |
| `release-integrity.json` | `2aef28b9b2b25a34a35c5f8661fa09453d2faedbb6839b11ba54460cbba947df` | 722 bytes |

The authors downloaded the artifact and computed these digests from the bytes.
The manifest's wheel, sdist and SBOM digests match.

The digests differ from the earlier record for `217c113`
([`../evidence/release-integrity-main-2026-09-27.md`](../evidence/release-integrity-main-2026-09-27.md))
because the source commit and its timestamp differ. Reproducibility is claimed
per commit, not across commits.

## Not done

- No GitHub release exists. The only tag is `v0.2.0`. The verified
  distributions, SBOM and manifest have not been attached to a release tag,
  and the artifact expires on the date above unless retained.
- Artifacts are not signed and have no provenance attestation.
