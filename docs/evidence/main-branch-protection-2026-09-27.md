# Main Branch Protection Evidence

Observed: 2026-09-27. Repository: `MCamner/atlas-core`. Main commit at
observation: `5964bb2e74d463fab35d714418814bad40658df5`.

Evidence was read through the authenticated GitHub REST API. No credentials or
token values are part of this record.

## Classic Branch Protection

Endpoint: `GET /repos/MCamner/atlas-core/branches/main/protection`.

| Setting | Observed value | Interpretation |
| --- | --- | --- |
| Pull request required | Yes (`required_pull_request_reviews` is present) | Direct updates must use the protected PR path |
| Required approvals | 0 | A PR is required, but this rule does not require a human approval |
| Stale approvals dismissed | Yes | New commits invalidate existing approvals if any are added later |
| Required status check | `python` | The repository test workflow is required |
| Strict status checks | Yes | The PR must be current with its base before merge |
| Enforce for administrators | Yes | Administrators are also subject to the protection |
| Force pushes | Disabled | Protected branch cannot be force-pushed |
| Branch deletion | Disabled | Protected branch cannot be deleted |
| Push restrictions | `null` | No named user/team restriction list was returned |

Endpoint: `GET /repos/MCamner/atlas-core/rulesets` returned an empty array.
The protection observed here is classic branch protection, not a repository
ruleset. The endpoint did not return a separate bypass-actor list; no such list
is claimed by this document.

## Main CI Evidence

The `test` workflow completed successfully on the exact main commit above:

- Run: [36288058236](https://github.com/MCamner/atlas-core/actions/runs/36288058236)
- Workflow: `test`
- Conclusion: `success`
- Head SHA: `5964bb2e74d463fab35d714418814bad40658df5`

## Limits

This API snapshot verifies the settings returned at the observation time; it is
not an independent security review. Zero required approvals means the branch
protection does not itself require reviewer sign-off. Repository-wide GitHub
Advanced Security settings and control-plane changes after this observation are
not covered. The security P2 checkbox and v2.0 exit gate remain open pending an
independent review and the remaining release-closure requirements.
