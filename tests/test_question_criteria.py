"""P1.1 box three: criteria that come from the question, not just the route.

`repo_review` declares what any review owes. It cannot declare what *this*
review owes, because until box one there was no "this": every run of the route
was graded against the same list whatever it had been asked.

The criterion added here comes from the question: a run whose plan narrowed to
a topic must settle something about a source that topic named. The requirement
text is the question, verbatim, so the run document says what the answer was
about rather than leaving a reader to infer it from a code.

It is a **relevance gate**, and it is named for what it checks rather than for
what one might wish it checked. `TestWhatTheGateDoesNotDecide` pins the
distance: a trivially true claim about the right file clears it. Closing that
distance is entailment, which nothing here decides, so P1.1 box three stays
open — see ROADMAP.md.

Two tests carry the behaviour the gate does change:

- a long, well-formatted, cited and verified answer about the wrong file falls
- a short answer that settles something about the right file passes
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
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
from atlas_core.review_plan import build_review_plan
from atlas_core.snapshot import collect_observation, take_snapshot

SETTINGS = "SERVICE_NAME=demo\nPASSWORD=admin\nTIMEOUT=30\n"
README = "# Demorepo\n\nEtt litet repo utan installationsavsnitt.\n"

SECRETS_TASK = "granska repot efter hårdkodade lösenord"
BROAD_TASK = "granska repo och säg något klokt"

LIMITS = RunLimits(
    wall_seconds=30, model_calls=6, tool_calls=0, tokens=100, output_bytes=600_000
)

SECTIONS = (
    "\n## Recommendation\nTa bort lösenordet.\n\n"
    "## Next step\nRotera nyckeln.\n\n## Confidence\nHög.\n"
)

LONG_PROSE = (
    "Granskningen nedan bygger på de källor som lästes denna körning och går "
    "igenom repots konfiguration, dokumentation och släppprocess i betydande "
    "detalj, med resonemang om varje steg, så att formen inte ska kunna "
    "anklagas för att vara det som fällde den. " * 3
)


class _Repo(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (self.root / "README.md").write_text(README, encoding="utf-8")
        (self.root / "settings.env").write_text(SETTINGS, encoding="utf-8")
        self.snapshot = take_snapshot(self.root)
        self.settings = collect_observation(self.snapshot, "settings.env")
        self.readme = collect_observation(self.snapshot, "README.md")
        self.base = EvidenceBase(
            snapshot=self.snapshot, observations=[self.settings, self.readme]
        )

    def _finding(self, observation: Observation, text: str) -> dict[str, Any]:
        typed = TypedClaim(
            kind=ClaimKind.CONTAINS, source_id=observation.source_id, text=text
        )
        claim = typed.render(
            observation.path, observation.line_start, observation.line_end
        )
        line = next(
            index + 1
            for index, content in enumerate(observation.excerpt.splitlines())
            if text in content
        )
        return {
            "claim": claim,
            "scope": observation.path,
            "severity": "P1",
            "severity_rationale": "Mätfixtur.",
            "evidence": [
                {
                    "source_id": observation.source_id,
                    "content_sha256": observation.content_sha256,
                    "line_start": line,
                    "line_end": line,
                    "quoted": observation.excerpt.splitlines()[line - 1],
                }
            ],
            "typed_claim": {
                "kind": typed.kind.value,
                "source_id": typed.source_id,
                "text": typed.text,
            },
        }

    def _also_citing(
        self, finding: dict[str, Any], observation: Observation, text: str
    ) -> dict[str, Any]:
        """Add a second intact citation the typed claim was not checked against.

        A finding may legitimately cite more than one source — context for a
        reader, a neighbouring line, the place a value is consumed. Nothing
        about the extra citation is wrong; what must not follow from it is a
        verdict about a source the claim was never settled against.
        """
        line = next(
            index + 1
            for index, content in enumerate(observation.excerpt.splitlines())
            if text in content
        )
        finding["evidence"].append(
            {
                "source_id": observation.source_id,
                "content_sha256": observation.content_sha256,
                "line_start": line,
                "line_end": line,
                "quoted": observation.excerpt.splitlines()[line - 1],
            }
        )
        return finding

    def _output(self, findings: list[dict[str, Any]], *, long: bool) -> str:
        head = "# Repogranskning\n\n" + (LONG_PROSE if long else "Kort.")
        body = (
            head
            + "\n\n## Observed sources\n- `settings.env`\n- `README.md`\n\n## Findings\n"
            + "\n".join(f"- {f['claim']}" for f in findings)
            + SECTIONS
        )
        if not findings:
            return body
        return body + "\n```" + FINDINGS_FENCE + "\n" + json.dumps(findings) + "\n```\n"

    def _run(self, output: str, task: str = SECRETS_TASK) -> dict[str, Any]:
        """Two passes and a host, because box three composes with box one.

        The plan names patterns a repository of this shape might have, and
        this one has some of them. Only a host can establish that there is no
        `config*` here — Core does not list directories — so the first pass is
        spent on that read and the question is graded on the second.
        """
        return AtlasController(max_iterations=2, model_adapter=_Adapter(output)).run(
            task,
            evidence=self.base,
            json_mode=True,
            limits=LIMITS,
            observer=_Host(self.root, self.snapshot),
        )


class _Adapter:
    def __init__(self, output: str):
        self.output = output

    def execute(self, **kwargs: Any) -> ModelResult:
        return ModelResult(
            output=self.output,
            provider="test",
            model="fixture",
            metadata={"usage_tokens": "1"},
        )


class _Host:
    """Resolves the plan's patterns against the real directory."""

    def __init__(self, root: Path, snapshot: Any):
        self.root = root
        self.snapshot = snapshot

    def observe(self, request: Any) -> list[Observation]:
        from fnmatch import fnmatch

        names = sorted(
            path.name
            for path in self.root.iterdir()
            if path.is_file()
            and any(fnmatch(path.name, pattern) for pattern in request.patterns)
        )
        return [collect_observation(self.snapshot, name) for name in names]


class TestTheCompletionCriterion(_Repo):
    def test_a_well_formatted_answer_that_misses_the_question_falls(self):
        """Long, complete, cited, verified — and about the wrong file.

        The question is about credentials and names `*.env`. This answer
        establishes something true about `README.md` instead. Every older
        signal reads as success: sections present, citation intact, claim
        settled in its favour.
        """
        run = self._run(
            self._output([self._finding(self.readme, "# Demorepo")], long=True)
        )
        evaluation = run["evaluations"][-1]

        self.assertFalse(evaluation["passed"])
        # Both, not just relevance. Nothing was settled about a source the plan
        # named, so nothing existed to test against the topic's answering set
        # either — and met criteria are `declared - unmet`, so naming only the
        # first would report the second as met although nobody checked it.
        self.assertEqual(
            sorted(evaluation["unmet_criteria"]),
            ["findings_answer_the_question", "findings_are_on_topic"],
        )
        self.assertEqual(evaluation["citation_checks"][0]["verdict"], "verified")

    def test_a_short_answer_that_establishes_something_passes(self):
        """Barely any prose, one settled claim about a source the plan named."""
        output = self._output(
            [self._finding(self.settings, "PASSWORD=admin")], long=False
        )
        run = self._run(output)

        self.assertLess(len(output), 1200)
        self.assertEqual(run["stop_reason"], "passed")
        self.assertEqual(run["evaluations"][-1]["unmet_criteria"], [])


class TestTheCriterionCarriesTheQuestion(_Repo):
    def test_the_requirement_text_is_the_question_itself(self):
        plan = build_review_plan(SECRETS_TASK, self.snapshot.snapshot_id)
        criteria = dict(criteria_for("repo_review", plan))

        self.assertIn("findings_are_on_topic", criteria)
        self.assertIn(plan.question, criteria["findings_are_on_topic"])

    def test_the_requirement_text_does_not_claim_the_question_was_answered(self):
        """The code and its sentence both have to stay inside what was checked.

        A criterion named for the question, met, reads as the question having
        been settled. It was not: see `TestWhatTheGateDoesNotDecide`.
        """
        plan = build_review_plan(SECRETS_TASK, self.snapshot.snapshot_id)
        requirement = dict(criteria_for("repo_review", plan))["findings_are_on_topic"]

        self.assertIn("relevance gate", requirement)
        self.assertNotIn("answering:", requirement)

    def test_the_run_document_says_what_it_was_supposed_to_answer(self):
        """One document, two places: the plan carries the question and the
        evaluation names the criterion that went unmet. The next action
        repeats the question, because that is what the producer has to act on.
        """
        run = self._run(
            self._output([self._finding(self.readme, "# Demorepo")], long=True)
        )
        evaluation = run["evaluations"][-1]

        self.assertTrue(run["plan"]["review"]["question"])
        self.assertIn("findings_are_on_topic", evaluation["unmet_criteria"])
        self.assertEqual(evaluation["next_action"]["kind"], "answer_the_question")
        self.assertEqual(
            evaluation["next_action"]["details"]["question"],
            run["plan"]["review"]["question"],
        )


class TestWhenThereIsNoQuestion(_Repo):
    def test_a_task_that_never_narrowed_is_not_held_to_a_question(self):
        """A broad task is not punished for being broad.

        The plan reports that it could not narrow, so there is no question to
        be off-topic about and the criterion is not declared at all.
        """
        run = self._run(
            self._output([self._finding(self.readme, "# Demorepo")], long=True),
            task=BROAD_TASK,
        )

        self.assertNotIn("findings_are_on_topic", run["evaluations"][-1]["unmet_criteria"])
        self.assertEqual(run["stop_reason"], "passed")

    def test_a_route_with_no_review_plan_is_unchanged(self):
        criteria = dict(criteria_for("repo_review", None))

        self.assertNotIn("findings_are_on_topic", criteria)


class TestAnEmptyReviewNoLongerAnswersAQuestion(_Repo):
    """The empty-review trap, closed at the gate rather than in the trailer.

    A review that asserts nothing meets every criterion about what findings are
    worth — there are none to be worth anything. It does not answer the
    question it was asked, and with a narrowed plan that is now a criterion.
    """

    def test_an_empty_review_does_not_pass_a_narrowed_review(self):
        run = self._run(self._output([], long=True))

        self.assertFalse(run["evaluations"][-1]["passed"])
        self.assertIn("findings_are_on_topic", run["evaluations"][-1]["unmet_criteria"])

    def test_a_refuted_claim_does_not_count_as_an_answer(self):
        """The producer was wrong; that is not the same as the question being
        settled by what it wrote."""
        finding = self._finding(self.settings, "PASSWORD=admin")
        finding["typed_claim"]["kind"] = ClaimKind.LACKS.value
        typed = TypedClaim(
            kind=ClaimKind.LACKS,
            source_id=self.settings.source_id,
            text="PASSWORD=admin",
        )
        finding["claim"] = typed.render(
            self.settings.path, self.settings.line_start, self.settings.line_end
        )

        run = self._run(self._output([finding], long=True))
        evaluation = run["evaluations"][-1]

        self.assertEqual(evaluation["citation_checks"][0]["verdict"], "contradicted")
        self.assertIn("findings_are_on_topic", evaluation["unmet_criteria"])


class TestTheGateReadsTheSourceThatWasChecked(_Repo):
    """Relevance is decided by the claim, not by the company it keeps.

    The gate asks which source a settled claim is *about*. A finding's citation
    list is a different question — it is what a reader may need to see, and it
    can legitimately name sources the claim was never tested against. Reading
    the list instead of the claim made a spare citation enough to buy relevance
    for a claim about somewhere else.
    """

    def test_a_spare_citation_does_not_make_an_off_topic_claim_relevant(self):
        """The claim is settled against `README.md`; the plan named `*.env`.

        Every other signal is honest: both citations are intact, the verdict
        is `verified`, and the finding is exactly what it says it is. The one
        thing that must not happen is the credentials question reporting
        itself looked into.
        """
        finding = self._also_citing(
            self._finding(self.readme, "# Demorepo"), self.settings, "PASSWORD=admin"
        )
        run = self._run(self._output([finding], long=True))
        evaluation = run["evaluations"][-1]
        record = evaluation["citation_checks"][0]

        # The precondition, asserted so a later change cannot make this test
        # pass for the wrong reason: two intact citations, one settled claim.
        self.assertEqual(record["verdict"], "verified")
        self.assertEqual(len(record["statuses"]), 2)
        self.assertEqual(record["claim_check"]["checked"]["path"], "README.md")

        self.assertFalse(evaluation["passed"])
        self.assertIn("findings_are_on_topic", evaluation["unmet_criteria"])

    def test_the_same_finding_counts_when_the_claim_is_the_one_on_topic(self):
        """The other direction, so the fix is not simply 'two citations fail'.

        Same two sources, same two intact citations. The typed claim is about
        `settings.env` this time, and that is what makes it relevant.
        """
        finding = self._also_citing(
            self._finding(self.settings, "PASSWORD=admin"), self.readme, "# Demorepo"
        )
        run = self._run(self._output([finding], long=True))
        evaluation = run["evaluations"][-1]

        self.assertEqual(len(evaluation["citation_checks"][0]["statuses"]), 2)
        self.assertEqual(run["stop_reason"], "passed")
        self.assertIn("findings_are_on_topic", evaluation["met_criteria"])


class TestWhatTheGateDoesNotDecide(_Repo):
    """The limit this class used to pin, and the one that replaced it.

    It used to assert that `TIMEOUT=30` in `settings.env` cleared the gate:
    settled, about a source the plan named, and no answer to whether a
    credential is committed. That is now closed for `secrets`, which declares
    what would bear on its question — see `test_predicates_close_it` in
    `tests/test_question_predicates.py`.

    What is left is the declaration itself, and this class keeps pinning it.
    The judgement about what counts is made in advance, per topic, by a person.
    A topic that has not made it is held to relevance alone, and a credential
    that does not name itself matches nothing that was declared.
    """

    def test_a_topic_with_no_declared_answer_is_still_relevance_only(self):
        """`documentation` declares no answering set, so any settled claim
        about a source it named clears its gate.

        Not a defect and not an oversight: declaring a list for a question
        nobody has thought through would be worse, because the criterion would
        then pass or fail on a list assembled to have a list.
        """
        run = self._run(
            self._output([self._finding(self.readme, "# Demorepo")], long=True),
            task="granska dokumentationen i repot",
        )
        evaluation = run["evaluations"][-1]

        self.assertEqual(run["plan"]["review"]["topic"], "documentation")
        self.assertEqual(run["plan"]["review"]["answering"], [])
        self.assertIn("findings_are_on_topic", evaluation["met_criteria"])
        self.assertNotIn(
            "findings_answer_the_question",
            evaluation["met_criteria"] + evaluation["unmet_criteria"],
        )
        self.assertEqual(run["stop_reason"], "passed")


class TestSeverityRuleSurvives(_Repo):
    def test_an_unestablished_finding_still_loses_its_severity(self):
        """Box three's second half, kept from #36 and asserted here again."""
        finding = self._finding(self.settings, "PASSWORD=admin")
        finding.pop("typed_claim")
        finding["claim"] = "settings.env ser riskabel ut."

        record = self._run(self._output([finding], long=True))["evaluations"][-1][
            "citation_checks"
        ][0]

        self.assertNotEqual(record["verdict"], "verified")
        self.assertEqual(record["severity"], "unknown")
        self.assertEqual(record["declared_severity"], "P1")


if __name__ == "__main__":
    unittest.main()
