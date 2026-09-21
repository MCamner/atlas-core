# Measuring the loop against an answer key

ROADMAP.md P1.1 box two. A loop that grades its own output needs something
outside itself to be graded against, or the only thing anyone can say about it
is that it agreed with itself.

## What is measured, and what is not

**The gate, not a finder.** Atlas Core ships no live model, so the findings in
a run are whatever its producer emitted. These measurements answer: given
these findings, does the loop establish the ones the source supports, refuse
the ones it contradicts, and decline to dress up the rest?

Whether a model is any good at *noticing* the defects is a different question,
and it needs a live provider — P1.2. `atlas_core/benchmark.py` is the
instrument that measurement will use; it is not itself a claim about model
quality, and a precision of 1.0 below says nothing about one.

## The fixtures

Two small repositories under `tests/fixtures/`, identical in shape and
different in content, so the defect is the variable rather than the file list:

| | `repo_with_defects` | `repo_without_defects` |
| --- | --- | --- |
| `README.md` | no `## Installation` section | has one |
| `deploy.sh` | a `TODO` marks an unfinished safety check | check implemented |
| `settings.env` | `PASSWORD=admin` committed in plain text | reads from the environment |

Each carries `ground_truth.json`. A defect there is a **predicate the
deterministic checker can settle** — literal presence or absence over observed
lines, on a named path. A defect that cannot be written that way is not in the
key, because a benchmark whose key cannot be checked measures the reader's
opinion of the output rather than the output.

Matching is exact: a finding counts against a defect when its typed claim names
the same path, kind and text. Never by comparing prose, which would let a
generous reader score a vague sentence as a hit. A test asserts that every
declared defect is actually present in the one repository and absent from the
other, so the key itself is checked rather than trusted.

## The measurements

| Field | What it says |
| --- | --- |
| `asserted` | findings the output made at all, prose included |
| `verified` / `refuted` / `unestablished` | how the loop settled them |
| `found_defects` / `missed_defects` | ground-truth ids established, and not |
| `verified_non_defects` | true about the file, and not a defect. Noise, not a lie, and it needs a different fix from a refutation |
| `precision` | of what the run established, the share that is a known defect |
| `recall` | of the known defects, the share established |
| `evidence_backed_share` | of what the run asserted, the share it backed |
| `iterations`, `stop_reason`, `cost` | what it took |
| `overstates_completeness` | the run met its gate while asserting nothing |

`precision` is `None` rather than `0.0` when a run established nothing. Zero
would read as "it was wrong about everything", which is a measurement; absent
is the honest value.

## Results

Scripted producers, one pass each, `max_iterations=1`, on the task `granska
repo och hitta defekter`. No topic's keywords appear in it, so the review plan
reports that it could not narrow, and these runs are graded on the route's
criteria alone. The two rows at the bottom re-run the same fixture under a task
the plan *can* narrow — see **What the task changes**.

| Repo | Scenario | asserted | verified | refuted | precision | recall | backed | stop reason | overstates |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| with defects | all three claimed | 3 | 3 | 0 | 1.0 | 1.0 | 1.0 | `passed` | no |
| with defects | one claimed | 1 | 1 | 0 | 1.0 | 0.33 | 1.0 | `passed` | no |
| with defects | three + a true non-defect | 4 | 4 | 0 | 0.75 | 1.0 | 1.0 | `passed` | no |
| with defects | three + a prose claim | 4 | 3 | 0 | 1.0 | 1.0 | 0.75 | `max_iterations` | no |
| with defects | **empty review** | 0 | 0 | 0 | — | **0.0** | — | **`passed`** | **yes** |
| without defects | all three claimed | 3 | 0 | 3 | — | — | 0.0 | `max_iterations` | no |
| without defects | one claimed | 1 | 0 | 1 | — | — | 0.0 | `max_iterations` | no |
| without defects | three + a true non-defect | 4 | 1 | 3 | 0.0 | — | 0.25 | `max_iterations` | no |
| without defects | **empty review** | 0 | 0 | 0 | — | — | — | **`passed`** | **yes** |
| with defects, narrowed | **empty review** | 0 | 0 | 0 | — | **0.0** | — | **`no_progress`** | no |
| with defects, narrowed | the password claimed | 1 | 1 | 0 | 1.0 | 0.33 | 1.0 | `passed` | no |

Cost for the first row: 1 model call, 1 token, 1912 output bytes.

Two rows carry the finding worth stating plainly.

**Invented defects are refused.** On the clean repository the same three claims
that are true of the other one are false, each naming a real file with a real
citation. Only comparing them against the source tells them apart, and the loop
does: three refutations, nothing established, no pass.

**An empty review passes, at a full score, having missed every defect** — when
the task could not be narrowed. Three real defects sat in the files it read.
Asserting nothing is the right answer to "did your claims hold" — there were
none — and it is not an answer to "is this repository sound". Those two read
alike in a run document. `recall` is 0.0, `overstates_completeness` is true,
and the text trailer says in as many words that the run established nothing and
that this is not a statement about the sources.

## What the task changes

The last two rows are the same fixture and the same producers, asked `granska
repot efter hårdkodade lösenord`. That narrows to a topic, so the plan names
sources and the run owes `findings_are_on_topic` as well. The empty review now
**stops** — `findings_are_on_topic` unmet, next action `answer_the_question` —
and a single settled claim about the committed password passes, scoring `D3`
and nothing else.

Two consequences worth reading off the table rather than inferring:

- `overstates_completeness` is `no` on the narrowed empty review. The flag is
  `passed and asserted == 0`, and that run does not pass. The flag was a
  warning for a case the gate now closes, and it still covers the case the gate
  does not: a broad task, where there is no question to have left unanswered.
- The gate is only as narrow as the plan. `granska repo och hitta defekter`
  reaches no topic, so eight of the ten rows never exercise
  `findings_are_on_topic` at all. The topic comes from keyword matching, which
  is stated as a limit in ROADMAP.md P1.1 box one, and it is a limit of these
  numbers too.

## Limitations

- The producers are scripted. Nothing here measures a model.
- Three defects in one small repository is an answer key, not a dataset. It
  catches a regression in the gate; it does not characterise performance.
- Eight of the ten rows are graded without the question criterion, because
  their task narrows to nothing. They measure the route's criteria, which is
  most of the gate and not all of it.
- Only defects expressible as literal presence or absence are in the key. A
  real review makes claims that cannot be written that way, and the loop
  cannot settle those either — `insufficient_evidence` is the honest outcome
  and also the ceiling of what this phase reaches.
