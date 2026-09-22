"""P1.1 box four: what another pass has to rest on.

The box asks that a retry require a new observation, a new test or a changed
plan, and that an identical run stop `no_progress`. Taken literally that would
refuse a producer the chance to fix a malformed findings block, which needs
nothing new at all — the bytes are in hand and the fault is in the writing.

So the contract is stated per action rather than per run. `RETRY_CLASSES` says
what a pass after each `next_action` would rest on:

- **restatement** — everything the next pass needs is already here. Changed
  feedback is the point of another pass and it is enough.
- **investigation** — the next pass needs material the run does not hold.
  Feedback cannot produce bytes, so a run that cannot get the material stops
  instead of spending a pass to fail the same way.

A new test is not a third channel: it reaches a run as an observation through
its own adapter. A changed plan is the other channel, and it is a fact in the
run document rather than a claim about intent.
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
from atlas_core.evidence import FINDINGS_FENCE
from atlas_core.evidence_base import EvidenceBase
from atlas_core.observation import Observation
from atlas_core.snapshot import collect_observation, take_snapshot
from atlas_core.state import NEXT_ACTION_KINDS, RETRY_CLASSES, retry_class

SETTINGS = "SERVICE_NAME=demo\nPASSWORD=admin\nTIMEOUT=30\n"
README = "# Demorepo\n\nEtt litet repo.\n"

SECRETS_TASK = "granska repot efter hårdkodade lösenord"

LIMITS = RunLimits(
    wall_seconds=30, model_calls=8, tool_calls=0, tokens=200, output_bytes=800_000
)

SECTIONS = (
    "\n## Recommendation\nTa bort lösenordet.\n\n"
    "## Next step\nRotera nyckeln.\n\n## Confidence\nHög.\n"
)


class TestTheContractIsDeclaredNotInferred(unittest.TestCase):
    def test_every_action_says_what_a_retry_of_it_rests_on(self):
        """An unclassified kind would default to the permissive half."""
        self.assertEqual(set(RETRY_CLASSES), set(NEXT_ACTION_KINDS))

    def test_only_reading_needs_material_the_run_does_not_hold(self):
        """Stated as a list, because the split is the whole contract.

        Every other action is something the producer can do with what is
        already in the run. Holding those to a new-observation bar would stop
        a run that has everything it needs and only needs to say it.
        """
        investigation = [k for k in NEXT_ACTION_KINDS if retry_class(k) == "investigation"]

        self.assertEqual(investigation, ["observe_again"])
        self.assertEqual(retry_class("answer_the_question"), "restatement")
        self.assertEqual(retry_class("repair_findings_block"), "restatement")


class _Host:
    """Resolves the plan's patterns against the real directory."""

    def __init__(self, root: Path, snapshot: Any):
        self.root = root
        self.snapshot = snapshot
        self.calls = 0

    def observe(self, request: Any) -> list[Observation]:
        self.calls += 1
        names = sorted(
            path.name
            for path in self.root.iterdir()
            if path.is_file()
            and any(fnmatch(path.name, pattern) for pattern in request.patterns)
        )
        return [collect_observation(self.snapshot, name) for name in names]


class _Scripted:
    """One output per pass, the last repeating."""

    def __init__(self, *outputs: str):
        self.outputs = list(outputs)
        self.calls = 0

    def execute(self, **kwargs: Any) -> ModelResult:
        output = self.outputs[min(self.calls, len(self.outputs) - 1)]
        self.calls += 1
        return ModelResult(
            output=output,
            provider="test",
            model="scripted",
            metadata={"usage_tokens": "1"},
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

    def _finding(self, observation: Observation, text: str) -> dict[str, Any]:
        typed = TypedClaim(
            kind=ClaimKind.CONTAINS, source_id=observation.source_id, text=text
        )
        line = next(
            index + 1
            for index, content in enumerate(observation.excerpt.splitlines())
            if text in content
        )
        return {
            "claim": typed.render(
                observation.path, observation.line_start, observation.line_end
            ),
            "scope": observation.path,
            "severity": "P1",
            "severity_rationale": "Fixtur.",
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

    def _output(
        self, findings: list[dict[str, Any]], *, raw_block: str | None = None
    ) -> str:
        body = (
            "# Repogranskning\n\nGranskningen nedan går igenom det som frågan "
            "gäller i tillräcklig detalj för att motivera slutsatserna.\n\n"
            "## Observed sources\n- `settings.env`\n- `README.md`\n\n## Findings\n"
            + "\n".join(f"- {f['claim']}" for f in findings)
            + SECTIONS
        )
        if raw_block is not None:
            return body + "\n```" + FINDINGS_FENCE + "\n" + raw_block + "\n```\n"
        if not findings:
            return body
        return body + "\n```" + FINDINGS_FENCE + "\n" + json.dumps(findings) + "\n```\n"

    def _after_the_first_read(self, *outputs: str) -> tuple[str, ...]:
        """Prepend the pass the plan's own patterns cost.

        The credentials plan names `config*` and `.env*`, and this repository
        has neither. Only a host can establish that — Core does not list
        directories — so the first pass is always spent on `observe_again`,
        whatever the producer wrote. Tests about what happens *after* reading
        start one pass later, and say so here rather than counting evaluations
        and hoping.
        """
        return (self._output([]),) + outputs

    def _run(
        self,
        *outputs: str,
        host: bool = True,
        iterations: int = 3,
        observations: list[Observation] | None = None,
    ) -> dict[str, Any]:
        base = EvidenceBase(
            snapshot=self.snapshot,
            observations=(
                observations
                if observations is not None
                else [self.settings, self.readme]
            ),
        )
        self.producer = _Scripted(*outputs)
        self.host = _Host(self.root, self.snapshot)
        return AtlasController(
            max_iterations=iterations, model_adapter=self.producer
        ).run(
            SECRETS_TASK,
            evidence=base,
            json_mode=True,
            limits=LIMITS,
            observer=self.host if host else None,
        )


class TestARestatementNeedsNothingNew(_Repo):
    """A citation repair is not an investigation, and is not held to its bar."""

    def test_a_malformed_block_is_repaired_on_the_next_pass(self):
        """And is named before the question, which is the ordering regression.

        Nothing in this run is on topic, because nothing in it parsed. Ranked
        ahead of `repair_findings_block` — where `answer_the_question` first
        landed — the producer would be told to answer the question while the
        reason nothing was read sat unmentioned one line above.
        """
        run = self._run(
            *self._after_the_first_read(
                self._output([], raw_block="{not json"),
                self._output([self._finding(self.settings, "PASSWORD=admin")]),
            ),
            iterations=4,
        )

        broken = run["evaluations"][1]
        self.assertEqual(broken["next_action"]["kind"], "repair_findings_block")
        self.assertEqual(retry_class("repair_findings_block"), "restatement")
        # No new observation after that point, no plan change, and the pass
        # was granted anyway.
        self.assertEqual(self.host.calls, 1)
        self.assertEqual(self.producer.calls, 3)
        self.assertEqual(run["stop_reason"], "passed")

    def test_an_off_topic_answer_is_a_restatement_and_gets_its_pass(self):
        """`answer_the_question`, kept as an explicit case.

        The sources are in hand and the answer is about the wrong one. Asking
        for a read here would deadlock a run that already holds everything it
        needs — what is missing is a claim, not bytes.
        """
        run = self._run(
            *self._after_the_first_read(
                self._output([self._finding(self.readme, "# Demorepo")]),
                self._output([self._finding(self.settings, "PASSWORD=admin")]),
            ),
            iterations=4,
        )

        self.assertEqual(
            run["evaluations"][1]["next_action"]["kind"], "answer_the_question"
        )
        # One host round, at the start. Nothing was read for the retry.
        self.assertEqual(self.host.calls, 1)
        self.assertEqual(run["stop_reason"], "passed")


class TestAnInvestigationNeedsMaterial(_Repo):
    def test_without_a_host_the_run_stops_instead_of_trying_again(self):
        """`observe_again` with nobody able to observe. One pass, not three."""
        run = self._run(
            self._output([self._finding(self.settings, "PASSWORD=admin")]),
            host=False,
            observations=[],
        )

        self.assertEqual(run["evaluations"][0]["next_action"]["kind"], "observe_again")
        self.assertEqual(run["stop_reason"], "blocked")
        self.assertEqual(run["metadata"]["blocked"]["reason"], "no_new_material")
        self.assertFalse(run["metadata"]["blocked"]["observer_attached"])
        self.assertEqual(self.producer.calls, 1)

    def test_with_a_host_the_material_arrives_and_the_pass_is_granted(self):
        """The negative control: the rule stops runs that cannot proceed, not
        runs that can."""
        run = self._run(
            self._output([self._finding(self.settings, "PASSWORD=admin")]),
            observations=[],
        )

        self.assertEqual(run["evaluations"][0]["next_action"]["kind"], "observe_again")
        self.assertGreaterEqual(self.host.calls, 1)
        self.assertEqual(run["stop_reason"], "passed")

    def test_a_pattern_resolved_for_the_first_time_is_material(self):
        """Kept as an explicit case, because it is the one exception.

        `config*` matches nothing in this repository. The host comes back
        having read no new bytes, and the run has still learned something it
        had no other way to learn: that there is no such file. It can only
        happen once per pattern.
        """
        run = self._run(
            self._output([self._finding(self.settings, "PASSWORD=admin")]),
            observations=[self.settings, self.readme],
        )
        rounds = run["metadata"]["observation_rounds"]

        self.assertTrue(rounds)
        self.assertIn("config*", rounds[0]["patterns"])
        self.assertEqual(rounds[0]["added"], [])
        self.assertEqual(run["stop_reason"], "passed")


class TestIdenticalMaterialAndIdenticalFeedbackStops(_Repo):
    def test_the_same_failure_over_the_same_evidence_is_no_progress(self):
        run = self._run(
            *self._after_the_first_read(
                self._output([], raw_block="{not json"),
                self._output([], raw_block="{still not json"),
            ),
            iterations=5,
        )

        self.assertEqual(run["stop_reason"], "no_progress")
        self.assertEqual(
            run["metadata"]["no_progress"]["reason"], "unchanged_feedback"
        )
        self.assertEqual(run["metadata"]["no_progress"]["material"], "unchanged")
        self.assertEqual(
            run["metadata"]["no_progress"]["action"], "repair_findings_block"
        )

    def test_a_failure_that_moves_still_gets_another_pass(self):
        """Negative control. A gate that stops everything proves nothing."""
        run = self._run(
            *self._after_the_first_read(
                self._output([], raw_block="{not json"),
                self._output([self._finding(self.readme, "# Demorepo")]),
                self._output([self._finding(self.settings, "PASSWORD=admin")]),
            ),
            iterations=5,
        )

        self.assertEqual(self.producer.calls, 4)
        self.assertEqual(run["stop_reason"], "passed")


if __name__ == "__main__":
    unittest.main()
