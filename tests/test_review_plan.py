"""P1.1 box one: a plan that knows what it is asking, driven end to end.

The completion criterion for this box is one run: an evidence gap leads to a
*relevant* new read, and that read produces either a verified finding or a
reasoned stop. `TestTheWholeLoop` is that run. Everything above it is the
parts it needs.

The plan states three things the old step list could not: which state the
review is about, which question it is asking, and which sources that question
needs. Sources are **patterns**, not paths, because Core does not list
directories — the host resolves them, the same way it already resolves a
re-read request.
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
from atlas_core.evidence import FINDINGS_FENCE
from atlas_core.evidence_base import EvidenceBase
from atlas_core.observation import Observation
from atlas_core.observer import ObservationRequest
from atlas_core.review_plan import (
    MAX_PATTERNS,
    TOPICS,
    UNKNOWN_TOPIC,
    ReviewPlan,
    build_review_plan,
    unread_patterns,
)
from atlas_core.snapshot import collect_observation, take_snapshot

SETTINGS = "SERVICE_NAME=demo\nPASSWORD=admin\nTIMEOUT=30\n"
README = "# Demorepo\n\nEtt litet repo.\n"

LIMITS = RunLimits(
    wall_seconds=30, model_calls=4, tool_calls=0, tokens=100, output_bytes=400_000
)

PROSE = """# Repogranskning

Granskningen nedan bygger på de källor som lästes denna körning och går igenom
det som frågan gäller i tillräcklig detalj för att motivera slutsatserna.

## Observed sources
{sources}

## Findings
{findings}

## Recommendation
Ta bort lösenordet ur versionshanteringen.

## Next step
Rotera nyckeln.

## Confidence
Hög.
"""


class TestThePlanStatesItsQuestion(unittest.TestCase):
    def test_a_task_about_secrets_asks_about_secrets(self):
        plan = build_review_plan("granska repot efter hårdkodade lösenord", "snap-1")

        self.assertEqual(plan.topic, "secrets")
        self.assertIn("credential", plan.question)
        self.assertIn("*.env", plan.patterns)
        self.assertTrue(plan.narrowed())

    def test_a_task_about_documentation_asks_about_documentation(self):
        plan = build_review_plan("granska dokumentationen och installationen", "snap-1")

        self.assertEqual(plan.topic, "documentation")
        self.assertIn("README.md", plan.patterns)

    def test_a_task_it_cannot_narrow_says_so_instead_of_guessing(self):
        """The rule this codebase applies to provenance, applied to a question.

        Inventing a plausible question would send the host reading files nobody
        asked about, and then grade the answer against a question nobody posed.
        """
        plan = build_review_plan("gör något bra med det här", "snap-1")

        self.assertEqual(plan.topic, UNKNOWN_TOPIC)
        self.assertEqual(plan.patterns, [])
        self.assertFalse(plan.narrowed())
        self.assertIn("gör något bra", plan.question)

    def test_the_plan_binds_to_one_snapshot(self):
        with self.assertRaises(ValueError):
            ReviewPlan(snapshot_id="", topic="secrets", question="x?")

    def test_a_review_cannot_ask_for_everything(self):
        with self.assertRaises(ValueError):
            ReviewPlan(
                snapshot_id="snap-1",
                topic="secrets",
                question="x?",
                patterns=[f"p{index}" for index in range(MAX_PATTERNS + 1)],
            )

    def test_every_topic_states_a_question_and_something_to_read(self):
        for topic in TOPICS:
            with self.subTest(topic.code):
                self.assertTrue(topic.question.strip().endswith("?"))
                self.assertTrue(topic.patterns)
                self.assertTrue(topic.keywords)


class TestWhatIsStillUnread(unittest.TestCase):
    def test_a_pattern_with_nothing_under_it_is_unread(self):
        plan = build_review_plan("granska lösenord", "snap-1")

        self.assertIn("*.env", unread_patterns(plan, ["README.md"]))

    def test_one_file_under_a_pattern_answers_it(self):
        plan = build_review_plan("granska dokumentationen", "snap-1")

        self.assertNotIn("docs/*", unread_patterns(plan, ["docs/architecture.md"]))

    def test_an_unnarrowed_plan_is_never_waiting_on_a_read(self):
        plan = build_review_plan("gör något bra", "snap-1")

        self.assertEqual(unread_patterns(plan, []), [])


class _Repo(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (self.root / "README.md").write_text(README, encoding="utf-8")
        (self.root / "settings.env").write_text(SETTINGS, encoding="utf-8")
        self.snapshot = take_snapshot(self.root)

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
            "severity": "P0",
            "severity_rationale": "Ett committat lösenord är omedelbart utnyttjbart.",
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

    def _output(self, findings: list[dict[str, Any]], sources: list[str]) -> str:
        text = PROSE.format(
            sources="\n".join(f"- `{name}`" for name in sources) or "- inga",
            findings="\n".join(f"- {f['claim']}" for f in findings),
        )
        if not findings:
            return text
        return text + "\n```" + FINDINGS_FENCE + "\n" + json.dumps(findings) + "\n```\n"


class TestTheWholeLoop(_Repo):
    """The completion criterion for box one, as one run.

    The run starts with a snapshot and **no observations at all**. The plan
    asks about credentials and names `*.env`; nothing has been read, so the
    gap is real and specific. The host resolves the pattern, reads
    `settings.env`, and the second pass settles a claim against those bytes.
    """

    def test_a_gap_leads_to_a_relevant_read_and_then_a_verified_finding(self) -> None:
        test = self
        host_requests: list[ObservationRequest] = []
        read: list[Observation] = []

        class _Host:
            def observe(self, request: ObservationRequest, *, budget: object = None) -> list[Observation]:
                host_requests.append(request)
                # A host resolves the plan's patterns itself. Core named what
                # it needed; finding the files is the host's half.
                from fnmatch import fnmatch

                names = sorted(
                    path.name
                    for path in test.root.iterdir()
                    if any(fnmatch(path.name, p) for p in request.patterns)
                )
                found = [collect_observation(test.snapshot, name) for name in names]
                read.extend(found)
                return found

        class _Producer:
            def __init__(self) -> None:
                self.calls = 0

            def execute(self, **kwargs: Any) -> ModelResult:
                self.calls += 1
                if not read:
                    output = test._output([], [])
                else:
                    output = test._output(
                        [test._finding(read[0], "PASSWORD=admin")],
                        [read[0].path],
                    )
                return ModelResult(
                    output=output,
                    provider="test",
                    model="producer",
                    metadata={"usage_tokens": "1"},
                )

        producer = _Producer()
        run = AtlasController(max_iterations=2, model_adapter=producer).run(
            "granska repot efter hårdkodade lösenord",
            evidence=EvidenceBase(snapshot=self.snapshot),
            json_mode=True,
            limits=LIMITS,
            observer=_Host(),
        )

        # 1. The plan is in the run document, with its question.
        plan = run["plan"]["review"]
        self.assertEqual(plan["topic"], "secrets")
        self.assertIn("*.env", plan["patterns"])
        self.assertEqual(plan["snapshot_id"], self.snapshot.snapshot_id)

        # 2. The first pass could not answer it, and said which sources were
        #    missing rather than that the answer was poorly worded.
        first = run["evaluations"][0]
        self.assertIn("plan_targets_read", first["unmet_criteria"])
        self.assertEqual(first["next_action"]["kind"], "observe_again")
        self.assertEqual(first["next_action"]["actor"], "host")

        # 3. The read was relevant: the host was asked for the plan's patterns
        #    and nothing else, and it read the file that carries the answer.
        self.assertEqual(host_requests[0].patterns, plan["patterns"])
        self.assertIn("settings.env", [o.path for o in read])

        # 4. The second pass settled a claim against those bytes.
        self.assertEqual(producer.calls, 2)
        self.assertEqual(run["stop_reason"], "passed")
        record = run["evaluations"][-1]["citation_checks"][0]
        self.assertEqual(record["verdict"], "verified")
        self.assertIn("PASSWORD=admin", record["statuses"][0]["quoted"])
        self.assertEqual(record["severity"], "P0")

    def test_without_a_host_the_same_gap_is_a_reasoned_stop(self):
        """The other half of the criterion. No read available, no pretending."""

        empty = self._output([], [])

        class _Producer:
            def execute(self, **kwargs: Any) -> ModelResult:
                return ModelResult(
                    output=empty,
                    provider="test",
                    model="producer",
                    metadata={"usage_tokens": "1"},
                )

        run = AtlasController(max_iterations=2, model_adapter=_Producer()).run(
            "granska repot efter hårdkodade lösenord",
            evidence=EvidenceBase(snapshot=self.snapshot),
            json_mode=True,
            limits=LIMITS,
        )

        self.assertFalse(run["evaluations"][-1]["passed"])
        self.assertIn("plan_targets_read", run["evaluations"][-1]["unmet_criteria"])
        self.assertEqual(
            run["evaluations"][-1]["next_action"]["kind"], "observe_again"
        )

    def test_a_task_it_cannot_narrow_does_not_demand_a_read(self):
        """Negative control: the gap is the plan's, not a new failure mode.

        An unnarrowed plan names no sources, so it cannot be waiting on one.
        Failing the run here would punish a task for being broad.
        """

        empty = self._output([], [])

        class _Producer:
            def execute(self, **kwargs: Any) -> ModelResult:
                return ModelResult(
                    output=empty,
                    provider="test",
                    model="producer",
                    metadata={"usage_tokens": "1"},
                )

        run = AtlasController(max_iterations=1, model_adapter=_Producer()).run(
            "granska repo och säg något klokt",
            evidence=EvidenceBase(snapshot=self.snapshot),
            json_mode=True,
            limits=LIMITS,
        )

        self.assertNotIn(
            "plan_targets_read", run["evaluations"][-1]["unmet_criteria"]
        )
        self.assertEqual(run["plan"]["review"]["topic"], UNKNOWN_TOPIC)


class TestOtherRoutesKeepTheirPlan(unittest.TestCase):
    def test_a_route_without_a_review_contract_carries_no_review_plan(self):
        run = AtlasController(max_iterations=1).run("hej", json_mode=True)

        self.assertIsNone(run["plan"]["review"])
        self.assertEqual(run["plan"]["steps"], ["understand", "answer", "next_step"])


if __name__ == "__main__":
    unittest.main()
