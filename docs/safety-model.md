# Safety Model

Atlas Core is read-only by default.

It must not commit, push, merge, create branches, open PRs, create issues, edit/delete files, or change settings without explicit user approval.

Detection in v0.1 is keyword-based and conservative. Future versions should use structured action classification.
