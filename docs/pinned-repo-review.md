# The loop against a real repository

ROADMAP.md P1.1 box five. Every measurement before this one ran against
fixtures this repository wrote. A fixture is built to be checkable, which is
what makes it useful and also what makes it unable to tell you whether the
loop survives contact with a repository nobody arranged.

## Reproducing it

```sh
git clone https://github.com/MCamner/mq-image-analyze /tmp/mq-image-analyze
git -C /tmp/mq-image-analyze checkout e5c4064733c4fced62b71f47e7b16e9335168532
python3 scripts/pinned_repo_review.py /tmp/mq-image-analyze
```

The script refuses nothing and asserts nothing; it prints the run. If the
checkout is at another commit it says so on stderr, because the numbers below
are about one state.

## What was run

`MCamner/mq-image-analyze` at commit
`e5c4064733c4fced62b71f47e7b16e9335168532` (18 September 2026), cloned to a
scratch directory and checked out at that commit. **Read-only**: nothing was
written to the repository or to the remote.

The snapshot bound to it reports `commit: e5c4064…`, `ref: HEAD`,
`worktree_state: clean`, so every claim below is about one state and says
which.

The question, from the plan rather than from the operator:

> Does the CI configuration run the checks it claims to run?

The task given was `granska repot mq-image-analyze: lokal och CI gate-paritet`.
The producer is not a model — Atlas Core ships none — so the findings are the
operator's, written as typed claims. What is being measured is whether the loop
**establishes or refuses** them, not whether anything is good at noticing them.

## What the loop established

One run, two iterations, `stop_reason: passed`. The first pass had read
nothing, so the plan's patterns were unmet and the next action was
`observe_again` with `actor: host`. The host resolved
`.github/workflows/*`, `Makefile` and `*.yml`, read seven files, and the
second pass was settled against those bytes.

| Verdict | Claim |
| --- | --- |
| `verified` | `.github/workflows/gate-parity.yml` lines 1-35 contain `./release-check.sh --json` |
| `verified` | `.github/workflows/gate-parity.yml` lines 1-35 contain `--self-test` |
| `verified` | `.github/workflows/tests.yml` lines 1-47 contain `pytest tests/ -v --tb=short` |
| `verified` | `.github/workflows/markdownlint.yml` lines 1-23 contain `globs: "**/*.md"` |

## The answer to the question asked

**What parity can be established from the tree at this commit.**

The strongest fact is the first one above. `gate-parity.yml` runs
`./release-check.sh --json` and asserts `status == "READY"`, so the whole local
gate executes in CI. That makes parity *structural* for everything
`release-check.sh` does, rather than a claim maintained by hand — a local check
cannot drift out of CI without CI failing.

Beside it sits a second, weaker mechanism. `scripts/check-gate-parity.py` is a
static text check: it verifies that every workflow file is registered, that
step names match a hardcoded list exactly, and that certain command substrings
appear in the workflow text. It establishes that the **declarations** agree. It
does not compare behaviour, and does not claim to.

Three specific things that can be read off the tree:

- **CI has one step the local gate does not.** CI runs the parity script twice,
  once plainly and once with `--self-test`. `release-check.sh` line 116 runs it
  without `--self-test`. The mechanism has a place to document a CI-only
  *workflow* (`CI_ONLY`) and none for a CI-only *step*. Reasonable here — a
  self-test of the checker is not a release gate — but undeclared.
- **The parity check runs before the pinned interpreter is set up.** In
  `gate-parity.yml`, `Validate gate parity` and `Test parity failures` are
  steps 2 and 3; `Set up Python` is step 4. Both therefore run on the runner's
  default `python3`, not the 3.12 the job pins.
- **The local gate covers one interpreter, CI covers two.** `tests.yml` runs a
  matrix of `3.11` and `3.12`; `release-check.sh` resolves a single `$PYTHON`
  (`.venv/bin/python`, falling back to `python`). A green local gate therefore
  cannot establish 3.11 compatibility.

**What cannot be established from the tree.**

That any of it ran, or passed. A workflow file is a declaration; a run result
is not in the repository. At this commit the check runs were in fact all
`success` (`test (3.11)`, `test (3.12)`, `parity`, `examples`, `markdownlint`),
but that came from the GitHub API, which is outside anything the loop observed
and outside anything a snapshot can carry.

That local and CI *behave* the same. `check-gate-parity.py` matches strings.

## Checked, and did not hold up

Recorded because a review that only reports what it found is not evidence of
looking. Neither of these became a finding.

- **markdownlint scope.** `release-check.sh` says in a comment that no globs
  are passed because "the action and this both read
  `.markdownlint-cli2.jsonc`", while `markdownlint.yml` does pass
  `globs: "**/*.md"`. That looked like a documented-versus-actual gap. It is
  not: `.markdownlint-cli2.jsonc` declares `"globs": ["**/*.md"]`, the same
  set, and `ignores` applies either way.
- **The test command differs.** Local is `pytest -q`, CI is
  `pytest tests/ -v --tb=short`. Different invocations, same test set:
  `pyproject.toml` sets `testpaths = ["tests"]`, and no test files live outside
  `tests/`.

## What the loop could not reach, and why

Three separate mechanisms, all of which a manual check walked straight past.
These are findings about Atlas Core, not about the repository under review.

**1. The question never reaches a plan unless the task says "repo".**
`select_route` and `build_review_plan` use two independent keyword
vocabularies, and nothing checks that they agree. `granska CI-workflow och
release-gate` selects `general` — no review plan, no patterns, no reading, no
evidence criteria — while `build_review_plan` on the same string returns topic
`ci`. The topic the plan would have asked about is computed and discarded. The
run above only worked because the task was reworded to contain `repot`.

**2. The `ci` topic's patterns do not name the local gate.** They are
`.github/workflows/*`, `Makefile` and `*.yml`. `release-check.sh` matches none
of them, so a question about *local versus CI* parity can only ever read the CI
half through the plan. Everything established above about the local gate was
read by hand.

**3. The observation bound stops before the local gates.**
`DEFAULT_MAX_LINES` is 80. `release-check.sh` is 169 lines and its gate
invocations are on lines 104–138. Had the plan named the file, the observation
would still have missed them.

That third one carries the sharpest risk in the system, and it is worth stating
precisely. A claim that `release-check.sh` *lacks* `run "pytest"` would be
settled `verified` against the excerpt, because the excerpt ends at line 80 and
the line is at 104. The rendering is honest — it reads
`release-check.sh lines 1-80 do not contain "run \"pytest\""`, naming the range
that was searched — so the document does not lie. It is still a sentence a
reader can summarise as "the gate does not run pytest", which is false of the
file.

## Against the fixture measurement

`docs/benchmark.md` reports precision, recall and a share of evidence-backed
findings against an answer key. None of that applies here and the difference is
not a detail:

- **There is no answer key.** Nobody planted a defect, and none was assumed. So
  there is no recall to report, and "four verified findings" is not a score.
- **The producer is the operator, not a model or a script.** The fixture rows
  measure the gate against outputs written to exercise it. This run measures
  the gate against claims written from reading a real repository, which is a
  different and smaller thing: it shows the machinery settles true claims and
  says which bytes settled them.
- **The fixture never exercised the router.** Its task string was chosen once
  and reached `repo_review` every time. The routing gap above is invisible to
  every row in that table, and to all 563 tests.

## Limitations

- One repository, one commit, one question. This is a contact test, not a
  characterisation.
- The four established findings are all `source_contains_literal`. The
  interesting parity conclusions above — that CI running `release-check.sh`
  makes parity structural, that a string match is not a behaviour match — are
  reasoning over what was read. The loop settles the reads; it does not settle
  the reasoning, and nothing in the run document claims it does.
- The findings carry `P2` because they record what is declared. Nothing here
  asserts a defect in `mq-image-analyze`.
