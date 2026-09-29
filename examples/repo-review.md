# Example: Repo Review

`atlas run "granska mqobsidian och hitta P0/P1/P2 förbättringar"`

Expected route: `repo_review`.

Without a model, a question that narrows to a review topic (CI, release) is
answered only in the shapes listed in
[`docs/api-contract.md`](../docs/api-contract.md#reading-again-mid-run). Other
wordings of the same question stop `blocked` with `no_on_topic_finding`
(or `budget_exhausted` near the byte limit), not `passed`.
