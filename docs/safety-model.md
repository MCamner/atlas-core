# Safety Model

Atlas Core is read-only by default. This document states where that boundary is
actually enforced by code, and where it is only advisory.

## Enforced

The read-only boundary is enforced by absence, not by a permission check.

- The package ships no LLM provider, no shell adapter, no network write path,
  and no write adapter. Nothing in `atlas_core/` can commit, push, merge, create
  a branch, open a PR, create an issue, or edit a file in your repository.
- The only code in the package that writes to disk is
  [`save_local_memory`](../atlas_core/memory.py), and it writes nothing unless
  you pass `--memory-dir`. It then creates that directory and one JSON file per
  run inside it. It writes nowhere else.

## Read paths

Reading is broader than writing, and it is worth knowing what each adapter touches.

- `FilesystemRepoAdapter` reads a fixed list of candidate files (`README.md`,
  `pyproject.toml`, `docs/*`, workflow files) under the path you pass to
  `--repo-path`. The file list is fixed; the root path is not validated, so the
  adapter reads wherever you point it.
- `GitHubRepoAdapter` issues HTTP GETs against `api.github.com` for the same
  file list. Unauthenticated by default. If `GITHUB_TOKEN` or `GH_TOKEN` is set
  in the environment, it is sent as a bearer token on those requests. The
  `owner/name` and `--repo-ref` values are interpolated into the request URL
  with no validation beyond requiring a `/` in the repo name.
- Every observation an adapter returns is rendered into the run output under
  `## Sources inspected`, and into the JSON run log under `observations`.

## Advisory only

Write-action detection is a signal, not a gate.

- [`requires_write_approval`](../atlas_core/safety.py) matches a fixed list of
  Swedish and English substrings (`commit`, `push`, `öppna pr`, `radera`, …)
  against the task string.
- On a match, the evaluator sets `requires_user_approval`, the controller stops
  the loop with status `need_user_approval`, the notice is recorded in
  `metadata.safety_notice`, and the finalizer prints
  `Write approval required before any mutation.`
- This blocks nothing, because nothing in the core can mutate anything. It
  exists so that an adapter which *can* write has a defined place to stop and
  ask. Any such adapter must honour `requires_user_approval` itself.

Known limits of the detection:

- It is literal substring matching. A paraphrase the list does not contain
  ("lägg upp ändringen", "ship it") is not detected.
- It reads only the task string. It does not inspect plans, observations, or
  adapter output.
- It has no notion of severity. `delete` and `publicera` are treated alike.

## Data handling

- Run output embeds observed repository content verbatim, including README text
  and file paths from your local checkout. Check a run log before sharing it.
- Local memory candidates are plain JSON, not encrypted.
- The `public_safe` field on a memory candidate is hardcoded to `true` in v0.2.
  It is a placeholder for a future check, not a verdict. Do not gate sharing on
  it.

## Workflow runner

`.github/workflows/run-atlas.yml` requests only `contents: read` and
`actions: read`, and passes its `workflow_dispatch` inputs to the shell through
environment variables rather than `${{ }}` interpolation, so an input containing
quotes or a semicolon cannot execute as a command on the runner.

## Not yet implemented

Structured action classification instead of keyword matching, and a derived
rather than hardcoded `public_safe` verdict.
