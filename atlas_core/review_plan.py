"""A repo review that knows what it is asking, and what it needs to read.

ROADMAP.md P1.1 box one. The plan a run carried was a list of step names —
`observe_repo`, `summarize`, `find_gaps` — fixed per route and identical for
every task that reached it. It said what the route generally does. It never
said what *this* run was looking into, which files that question needed, or
when the answer was in.

A `ReviewPlan` says three things instead:

- **which state** the review is about. The plan does not go and take a
  snapshot: it binds to the one the run already carries and records its id, so
  the whole review is about one state and says which. Taking a snapshot is
  reading, and reading belongs to the host.
- **which question** is being asked, in one sentence, derived from the task.
- **which sources** that question needs, as patterns rather than paths.

Patterns, not paths, because Core does not list directories any more than it
opens sockets. The host resolves a pattern against the snapshot and reads what
it finds — the same division of labour the observation loop already uses, and
the reason this reuses that loop rather than growing a second one.

## When it cannot narrow

A task that matches no topic gets `UNKNOWN_TOPIC`: the question is the task
itself, the pattern list is empty, and the plan says it could not narrow. That
is the same discipline `Observation.v1` applies to provenance — a field that
cannot be established says so instead of being filled with something
plausible. A plan that invented a question would send the host reading files
nobody asked about and then grade the answer against a question nobody posed.

## What this is not

It does not decide whether the question was *answered*. Criteria derived from
the question are box three, and they need this to exist first. This plan
states the question and names what it takes to look into it; the evaluator
still grades on the route's criteria.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

SCHEMA = "atlas-review-plan.v1"

#: The stand-in for a question this plan could not narrow. Same word, same
#: reason, as everywhere else in this codebase.
UNKNOWN_TOPIC = "unknown"

#: How many source patterns one review may ask for. A review that wants
#: everything has not chosen a question, and an unbounded first read is an
#: unbounded first cost.
MAX_PATTERNS = 6


@dataclass(frozen=True)
class ReviewTopic:
    """One kind of question a repo review can ask, and what it takes to answer.

    `keywords` are matched against the task, lowercased. Swedish and English
    both appear because both appear in the tasks this repository is given.
    """

    code: str
    question: str
    keywords: tuple[str, ...]
    #: Glob patterns, relative to the snapshot root, for the host to resolve.
    patterns: tuple[str, ...]
    #: Literals a settled claim must name for that claim to bear on this
    #: topic's question. **Declared, not inferred**: the judgement about what
    #: answers the question is made here, once, where it can be read and
    #: disagreed with — not derived from the claim at grading time, which would
    #: be entailment, which needs a model.
    #:
    #: Empty means this topic has not declared one. A topic with no answering
    #: set is held to relevance only: something settled about a source it
    #: named. Declaring a set for a question nobody has thought through would
    #: be worse than declaring none, because the criterion would then pass or
    #: fail on a list assembled to have a list.
    answering: tuple[str, ...] = ()


#: Ordered: the first topic whose keywords appear in the task wins. Order is by
#: specificity, not importance — "installationsinstruktioner" is a
#: documentation question and also contains "instruktion", so the narrower
#: topic has to be reachable.
TOPICS: tuple[ReviewTopic, ...] = (
    ReviewTopic(
        code="secrets",
        question=(
            "Does this repository commit a credential, a default password or a "
            "token in plain text?"
        ),
        keywords=(
            "secret", "hemlig", "lösenord", "losenord", "password", "token",
            "credential", "nyckel",
        ),
        patterns=("*.env", "settings*", "config*", ".env*"),
        # An assignment, not a mention. `PASSWORD=admin` names a credential
        # being set; `TIMEOUT=30` in the same file is true, settled, about a
        # source this topic named, and says nothing about whether a credential
        # is committed. That pair is the completion criterion in ROADMAP P1.1.
        #
        # The limit is worth stating where the list is: a credential that does
        # not name itself — a bare `AKIA…` key, a base64 blob — matches none of
        # these and is a miss. Fail-closed: the run stops and asks for an
        # answer rather than passing on something unrelated.
        answering=(
            "password=", "passwd=", "pwd=", "lösenord=", "secret=",
            "token=", "api_key=", "apikey=", "access_key=", "private key",
        ),
    ),
    ReviewTopic(
        code="ci",
        question="Does the CI configuration run the checks it claims to run?",
        keywords=("ci", "workflow", "actions", "pipeline", "bygge", "build"),
        patterns=(".github/workflows/*", "Makefile", "*.yml"),
    ),
    ReviewTopic(
        code="tests",
        question="Is there a test suite, and does the project say how to run it?",
        keywords=("test", "tester", "täckning", "tackning", "coverage", "suite"),
        patterns=("tests/*", "test_*", "pyproject.toml", "README.md"),
    ),
    ReviewTopic(
        code="release",
        question=(
            "Do the version, the changelog and the release process agree with "
            "each other?"
        ),
        keywords=("release", "släpp", "slapp", "version", "changelog", "tag"),
        patterns=("CHANGELOG.md", "pyproject.toml", "README.md"),
    ),
    ReviewTopic(
        code="documentation",
        question=(
            "Does the documentation say what this project is, how to install "
            "it and how to run it?"
        ),
        keywords=(
            "dokumentation", "docs", "readme", "installation", "installera",
            "install", "komma igång", "onboarding", "instruktion",
        ),
        patterns=("README.md", "docs/*", "CONTRIBUTING.md"),
    ),
)


@dataclass(frozen=True)
class ReviewPlan:
    """What this review is about, and what it needs to read to find out."""

    #: The state the review is about. One per run, recorded rather than taken.
    snapshot_id: str
    #: The topic code, or `unknown` when the task matched none.
    topic: str
    #: The question in one sentence. The task itself when nothing narrowed it.
    question: str
    #: Glob patterns the host resolves against the snapshot.
    patterns: list[str] = field(default_factory=list)
    #: Why these patterns, so a reader can disagree with the selection rather
    #: than only with the answer.
    rationale: str = ""
    #: The topic's declared answering literals, carried into the run document
    #: so a reader sees what the run was willing to accept as an answer.
    #: Empty when the topic declared none.
    answering: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.question.strip():
            raise ValueError("a review plan states a question")
        if not self.snapshot_id.strip():
            raise ValueError(
                "a review plan binds to one snapshot; a review of no particular "
                "state cannot say which bytes its answer is about"
            )
        if len(self.patterns) > MAX_PATTERNS:
            raise ValueError(
                f"a review asks for at most {MAX_PATTERNS} source patterns, got "
                f"{len(self.patterns)}; wanting everything is not a question"
            )

    def narrowed(self) -> bool:
        """Whether the task was understood well enough to look anywhere."""
        return self.topic != UNKNOWN_TOPIC

    def to_dict(self) -> dict[str, Any]:
        return {"schema": SCHEMA, **asdict(self)}


def build_review_plan(task: str, snapshot_id: str) -> ReviewPlan:
    """Work out what this review is asking, and what it takes to look.

    Deterministic, and narrow on purpose. There is no model here: the topic is
    chosen by keyword, which is a real mechanism and a limited one. Its limit
    is visible rather than hidden — a task that matches nothing is reported as
    not narrowed instead of being answered with a plausible-looking question
    about files nobody asked about.
    """
    text = task.lower()
    for topic in TOPICS:
        if any(keyword in text for keyword in topic.keywords):
            return ReviewPlan(
                snapshot_id=snapshot_id,
                topic=topic.code,
                question=topic.question,
                patterns=list(topic.patterns),
                rationale=(
                    f"The task names {topic.code}; these are the paths that "
                    "carry the answer in a repository of this shape."
                ),
                answering=list(topic.answering),
            )

    return ReviewPlan(
        snapshot_id=snapshot_id,
        topic=UNKNOWN_TOPIC,
        question=task.strip(),
        patterns=[],
        rationale=(
            "The task matched no known review topic, so no sources were "
            "selected. Naming files anyway would send a read after a question "
            "nobody asked."
        ),
    )


def answers_question(plan: ReviewPlan, claim_text: str) -> bool:
    """Whether a settled claim names something this topic calls an answer.

    Case-insensitive substring against the topic's declared literals. A narrow
    mechanism, and the narrowness is the point: deciding whether an arbitrary
    settled claim *answers* an arbitrary question is entailment, and a guess at
    it would sit behind a PASS. This asks a smaller question that has a
    definite answer — did the claim name one of the things declared in advance
    to count?

    A plan that declared nothing answers True. There is no set to be outside
    of, and failing every claim against an empty list would make the criterion
    unmeetable rather than strict.
    """
    if not plan.answering:
        return True
    text = claim_text.lower()
    return any(literal.lower() in text for literal in plan.answering)


def unread_patterns(
    plan: ReviewPlan,
    read_paths: list[str],
    resolved: list[str] | None = None,
) -> list[str]:
    """Which of the plan's patterns this run is still waiting on.

    A pattern is answered two ways, and both are needed.

    It is answered when some observation sits under it: one file under
    `docs/*` says the plan's `docs/*` was looked at. Whether one file is enough
    to answer the question is a judgement the evaluator makes, not this.

    It is also answered when a host was **asked to resolve it and came back**,
    even with nothing. A plan names patterns that suit a repository of a given
    shape, and a given repository may simply have no `config*` in it. Core
    cannot tell "no such file" from "not read yet" without listing the
    directory, which it does not do — the host can, and a completed round is
    that answer. Without this, a plan would wait forever on a file that does
    not exist and every review would end `insufficient_evidence`.
    """
    from fnmatch import fnmatch

    answered = set(resolved or [])
    return [
        pattern
        for pattern in plan.patterns
        if pattern not in answered
        and not any(fnmatch(path, pattern) for path in read_paths)
    ]


__all__ = [
    "MAX_PATTERNS",
    "SCHEMA",
    "TOPICS",
    "UNKNOWN_TOPIC",
    "ReviewPlan",
    "ReviewTopic",
    "answers_question",
    "build_review_plan",
    "unread_patterns",
]
