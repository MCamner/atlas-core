"""P1.1: a question with declared predicates, past the relevance gate.

`findings_are_on_topic` asks which *source* a settled claim is about. This asks
what the claim *names*. The difference is the whole item: a verified claim that
`settings.env` contains `TIMEOUT=30` is settled, is about a source the
credentials question named, and says nothing about whether a credential is
committed.

The judgement is **declared, not inferred**. `ReviewTopic.answering` lists the
literals that bear on the topic's question, written once where they can be read
and disagreed with. Deriving the same judgement from an arbitrary claim at
grading time is entailment, which needs a model, and a guess at it would sit
behind a PASS rather than beside a limitation.

Two limits, and both have a test below rather than only a sentence:

- a topic that declares nothing is held to relevance alone;
- a credential that does not name itself matches nothing that was declared, and
  the run stops rather than passing on something unrelated.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from atlas_core import AtlasController
from atlas_core.adapters.model import ModelResult
from atlas_core.budget import RunLimits
from atlas_core.claim_check import ClaimKind, TypedClaim
from atlas_core.evaluator import criteria_for
from atlas_core.evidence import FINDINGS_FENCE
from atlas_core.evidence_base import EvidenceBase
from atlas_core.observation import Observation
from atlas_core.review_plan import TOPICS, answers_question, build_review_plan
from atlas_core.snapshot import collect_observation, take_snapshot

SETTINGS = "SERVICE_NAME=demo\nPASSWORD=admin\nTIMEOUT=30\nAKIAIOSFODNN7EXAMPLE\n"
README = "# Demorepo\n\nEtt litet repo.\n"
SECRETS_TASK = "granska repot efter hårdkodade lösenord"

LIMITS = RunLimits(
    wall_seconds=30, model_calls=6, tool_calls=0, tokens=200, output_bytes=600_000
)

SECTIONS = (
    "\n## Recommendation\nTa bort lösenordet.\n\n"
    "## Next step\nRotera nyckeln.\n\n## Confidence\nHög.\n"
)


class TestTheSetIsDeclared(unittest.TestCase):
    def test_secrets_declares_what_bears_on_its_question(self):
        plan = build_review_plan(SECRETS_TASK, "snap-1")

        self.assertTrue(plan.answering)
        self.assertIn("password=", plan.answering)

    def test_the_pair_the_criterion_names(self):
        """`PASSWORD=admin` qualifies. `TIMEOUT=30` does not."""
        plan = build_review_plan(SECRETS_TASK, "snap-1")

        self.assertTrue(answers_question(plan, "PASSWORD=admin"))
        self.assertFalse(answers_question(plan, "TIMEOUT=30"))
        self.assertFalse(answers_question(plan, "SERVICE_NAME=demo"))

    def test_a_topic_that_declared_nothing_accepts_anything(self):
        """Not permissiveness by accident: an empty list is "not declared",
        and failing every claim against it would make the criterion
        unmeetable rather than strict."""
        plan = build_review_plan("granska dokumentationen", "snap-1")

        self.assertEqual(plan.answering, [])
        self.assertTrue(answers_question(plan, "vad som helst"))

    def test_the_requirement_text_lists_what_it_will_accept(self):
        """A criterion whose bar is a hidden list is a bar nobody can read."""
        plan = build_review_plan(SECRETS_TASK, "snap-1")
        criteria = dict(criteria_for("repo_review", plan))

        self.assertIn("findings_answer_the_question", criteria)
        self.assertIn("password=", criteria["findings_answer_the_question"])
        self.assertIn(plan.question, criteria["findings_answer_the_question"])

    def test_a_topic_without_a_set_declares_no_such_criterion(self):
        plan = build_review_plan("granska dokumentationen", "snap-1")

        self.assertNotIn(
            "findings_answer_the_question", dict(criteria_for("repo_review", plan))
        )

    def test_every_declared_literal_is_lowercase_and_non_empty(self):
        """Matching is case-insensitive; a stray uppercase entry would read as
        significant and never be."""
        for topic in TOPICS:
            for literal in topic.answering:
                with self.subTest(topic=topic.code, literal=literal):
                    self.assertEqual(literal, literal.lower())
                    self.assertTrue(literal.strip())


class _Host:
    def __init__(self, root: Path, snapshot: Any):
        self.root = root
        self.snapshot = snapshot

    def observe(self, request: Any) -> list[Observation]:
        names = sorted(
            p.name
            for p in self.root.iterdir()
            if p.is_file() and any(fnmatch(p.name, q) for q in request.patterns)
        )
        return [collect_observation(self.snapshot, n) for n in names]


class _Adapter:
    def __init__(self, output: str):
        self.output = output

    def execute(self, **kwargs: Any) -> ModelResult:
        return ModelResult(
            output=self.output, provider="test", model="fixture",
            metadata={"usage_tokens": "1"},
        )


class _Repo(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (self.root / "settings.env").write_text(SETTINGS, encoding="utf-8")
        (self.root / "README.md").write_text(README, encoding="utf-8")
        self.snapshot = take_snapshot(self.root)
        self.settings = collect_observation(self.snapshot, "settings.env")
        self.readme = collect_observation(self.snapshot, "README.md")
        self.base = EvidenceBase(
            snapshot=self.snapshot, observations=[self.settings, self.readme]
        )

    def _finding(
        self, text: str, observation: Observation | None = None
    ) -> dict[str, Any]:
        source = observation or self.settings
        typed = TypedClaim(
            kind=ClaimKind.CONTAINS, source_id=source.source_id, text=text
        )
        line = next(
            i + 1
            for i, content in enumerate(source.excerpt.splitlines())
            if text in content
        )
        return {
            "claim": typed.render(
                source.path, source.line_start, source.line_end
            ),
            "scope": source.path,
            "severity": "P1",
            "severity_rationale": "Fixtur.",
            "evidence": [
                {
                    "source_id": source.source_id,
                    "content_sha256": source.content_sha256,
                    "line_start": line,
                    "line_end": line,
                    "quoted": source.excerpt.splitlines()[line - 1],
                }
            ],
            "typed_claim": {
                "kind": typed.kind.value,
                "source_id": typed.source_id,
                "text": typed.text,
            },
        }

    def _run(
        self, text: str, observation: Observation | None = None
    ) -> dict[str, Any]:
        finding = self._finding(text, observation)
        body = (
            "# Repogranskning\n\nGranskningen går igenom det frågan gäller.\n\n"
            "## Observed sources\n- `settings.env`\n- `README.md`\n\n## Findings\n- "
            + finding["claim"]
            + SECTIONS
            + "\n```" + FINDINGS_FENCE + "\n" + json.dumps([finding]) + "\n```\n"
        )
        return AtlasController(
            max_iterations=2, model_adapter=_Adapter(body)
        ).run(
            SECRETS_TASK,
            evidence=self.base,
            json_mode=True,
            limits=LIMITS,
            observer=_Host(self.root, self.snapshot),
        )


class TestTwoRunsAgainstOneFile(_Repo):
    """The completion criterion, verbatim: same file, both verified, both about
    the source the plan named, and only one of them counts."""

    def test_the_committed_password_answers_it(self):
        run = self._run("PASSWORD=admin")
        evaluation = run["evaluations"][-1]

        self.assertEqual(evaluation["citation_checks"][0]["verdict"], "verified")
        self.assertIn("findings_answer_the_question", evaluation["met_criteria"])
        self.assertEqual(run["stop_reason"], "passed")

    def test_a_true_statement_about_the_same_file_does_not(self):
        run = self._run("TIMEOUT=30")
        evaluation = run["evaluations"][-1]

        # Every older signal still reads as success.
        self.assertEqual(evaluation["citation_checks"][0]["verdict"], "verified")
        self.assertIn("findings_are_on_topic", evaluation["met_criteria"])
        # And the run does not pass.
        self.assertFalse(evaluation["passed"])
        self.assertEqual(
            evaluation["unmet_criteria"], ["findings_answer_the_question"]
        )
        self.assertEqual(evaluation["next_action"]["kind"], "answer_the_question")


class TestNothingRelevantFailsBothCriteria(_Repo):
    """A criterion nobody checked must not be reported as met.

    Met criteria are `declared - unmet`, so naming only the relevance gap when
    nothing is on topic would leave `findings_answer_the_question` in the met
    list — and in `quality_score` — although no finding existed to test against
    the answering set. The run would stop either way; the reporting would be
    asserting something nobody established, which is the failure this whole
    phase exists to remove.
    """

    def test_a_secrets_review_with_nothing_on_topic_fails_both(self):
        run = self._run("# Demorepo", self.readme)
        evaluation = run["evaluations"][-1]

        self.assertEqual(evaluation["citation_checks"][0]["verdict"], "verified")
        self.assertEqual(
            sorted(evaluation["unmet_criteria"]),
            ["findings_answer_the_question", "findings_are_on_topic"],
        )
        self.assertNotIn(
            "findings_answer_the_question", evaluation["met_criteria"]
        )
        self.assertFalse(evaluation["passed"])

    def test_the_score_counts_it_as_unmet_too(self):
        """`quality_score` is the share met, so the miscount was visible there."""
        run = self._run("# Demorepo", self.readme)
        evaluation = run["evaluations"][-1]
        total = len(evaluation["met_criteria"]) + len(evaluation["unmet_criteria"])

        self.assertEqual(
            evaluation["quality_score"],
            round(len(evaluation["met_criteria"]) / total, 2),
        )

    def test_a_topic_with_no_answering_set_only_fails_the_one(self):
        """Negative control: `unmet &= declared` keeps the second out where the
        topic never declared it, so no special case is needed."""
        from atlas_core.evaluator import criteria_for

        plan = build_review_plan("granska dokumentationen", "snap-1")
        declared = [code for code, _ in criteria_for("repo_review", plan)]

        self.assertNotIn("findings_answer_the_question", declared)


class TestTheLimitOfDeclaringInAdvance(_Repo):
    """Pinned where the behaviour is, because this is what the mechanism cannot
    do and a roadmap note is easy to stop reading."""

    def test_a_credential_that_does_not_name_itself_is_a_miss(self):
        """`AKIAIOSFODNN7EXAMPLE` is a key. It matches nothing declared.

        Fail-closed, which is the right direction: the run stops and asks for
        an answer rather than passing on a claim about something else. It is
        still a miss, and a real one.
        """
        run = self._run("AKIAIOSFODNN7EXAMPLE")
        evaluation = run["evaluations"][-1]

        self.assertEqual(evaluation["citation_checks"][0]["verdict"], "verified")
        self.assertFalse(evaluation["passed"])
        self.assertIn(
            "findings_answer_the_question", evaluation["unmet_criteria"]
        )


if __name__ == "__main__":
    unittest.main()
