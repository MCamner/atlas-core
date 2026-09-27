# Main Release Integrity Evidence

Observed: 2026-09-27. Repository: `MCamner/atlas-core`.

## Source and CI

- Package: `atlas-core` `1.0.0`
- Main source commit: `217c113337c00f20e69a8afe75f4909f0e9763fe`
- Workflow: `test`
- Main run: [36288259356](https://github.com/MCamner/atlas-core/actions/runs/36288259356)
- Run result: `success` on the exact source commit above
- Artifact: `atlas-core-release-integrity` (available and not expired when observed)
- `SOURCE_DATE_EPOCH`: `1790475662`, derived from the source commit timestamp

The workflow built wheel and sdist in two detached worktrees at the same
commit, using the hash-locked `build` dependency group. It canonicalized only
sdist archive metadata (tar/gzip timestamps, owner/group fields and PAX time
entries); member file contents were not rewritten. The normalized wheel and
sdist SHA-256 values matched across both builds. The release SBOM is CycloneDX
1.5 and identifies the same package/version and source commit.

## Artifact Digests

| Artifact | Filename | SHA-256 | Size |
| --- | --- | --- | ---: |
| Wheel | `atlas_core-1.0.0-py3-none-any.whl` | `4f8b8ae9baf05d06e2e4abfb267fac8364ad8f7c40921ff70ea3f659dc5c9780` | 205083 bytes |
| Sdist | `atlas_core-1.0.0.tar.gz` | `8ec177fb2d228999cc389bb9a0a59821560be627e6653d91795db09eca938b85` | 349792 bytes |
| Release SBOM | `atlas-core-1.0.0.cdx.json` | `efdb9b402bf2e0119f409335c0d437fcd8ad21e701a19b836b4d41977f83dee0` | 1233 bytes |

`release-integrity.json` in the workflow artifact records the package/version,
source commit, source epoch, wheel/sdist hashes and SBOM hash. The hashes above
were independently compared with the downloaded artifact bytes.

This is CI release-integrity evidence, not a published release. Attaching the
verified distributions, SBOM and manifest to a release tag and retaining their
digests remains a separate release action.
