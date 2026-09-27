# Hosting Controls

Repository: `MCamner/atlas-core` (public). Observed 2026-09-27 through the
authenticated GitHub REST API, with `main` at the code security baseline
`6474f17d4ca6fa75d56f29d2475ad4bfcb1c7d60`. No token values are recorded.
The same values were read at `07ac394` earlier the same day.

## Branch protection on `main`

`GET /repos/MCamner/atlas-core/branches/main/protection`

| Setting | Observed |
| --- | --- |
| Pull request required | Yes |
| Required approvals | 0 |
| Dismiss stale approvals | Yes |
| Required status checks | `python` |
| Strict (branch must be up to date) | Yes |
| Enforce for administrators | Yes |
| Force pushes | Disabled |
| Deletion | Disabled |
| Push restrictions | `null` |

`GET /repos/MCamner/atlas-core/rulesets` returned an empty list.

The same values were recorded earlier at `5964bb2` in
[`../evidence/main-branch-protection-2026-09-27.md`](../evidence/main-branch-protection-2026-09-27.md).

## Repository security settings

`GET /repos/MCamner/atlas-core` → `security_and_analysis`

| Setting | Observed |
| --- | --- |
| Secret scanning | Enabled |
| Secret scanning push protection | Enabled |
| Secret scanning, non-provider patterns | Disabled |
| Secret scanning, validity checks | Disabled |
| Dependabot security updates | Disabled |

Dependabot version updates for `uv` and `github-actions` are configured in
`.github/dependabot.yml`.

## What this does not show

- With zero required approvals, a PR author with write access can merge their
  own PR once `python` passes. The repository is owned by a user account, and
  `GET /repos/MCamner/atlas-core/collaborators` listed one collaborator,
  `MCamner` (`admin`). Nothing in the hosting configuration requires a second
  person.
- The account's security settings (2FA, tokens, apps with repository access)
  and the audit log were not examined.
- Settings can change after the observation time. The reviewer should re-read
  them when the review is done.
