"""v1.3 box two: the append-only log, and what it can honestly attest.

The log's job is not to be complete. It is to be **unambiguous about its own
gaps**, because the work that comes after it — resume, and not repeating a side
effect — has to act on what it says.

So the assertions here are mostly about three states and the difference between
them:

    no `call_started`                  the call never began
    `call_started`, no `call_finished` it began; the outcome is UNKNOWN
    both                               it began and the outcome is recorded

A design with one record per call collapses the middle into one of the other
two, and both readings are dangerous. "Failed" invites a retry that repeats a
side effect the first attempt may already have had; "never happened" is worse.
`unknown` is the honest answer and the whole reason a call is two events.

The rest is the append-only rule enforced rather than intended — the log
assigns positions, nothing rewrites one, and an observation recorded twice is
two records — plus the fact that this file persists on disk, which makes it one
more channel a source's bytes can reach.

**Not in scope:** resume itself. No locking, no replay, no `interrupted` or
`resumed` events. This box records enough for the next one to tell the three
states apart, and stops.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any

from atlas_core import AtlasController, StubModelAdapter
from atlas_core.adapters.model import ModelResult
from atlas_core.budget import RunLimits
from atlas_core.eventlog import (
    CALL_OUTCOMES,
    EVENT_KINDS,
    AppendOnlyViolation,
    Event,
    EventLog,
    JsonlSink,
    TornLogTail,
    call_states,
    digest,
    read_jsonl,
    unfinished_calls,
)
from atlas_core.tool_gateway import ToolDefinition

from test_observe_again import (
    LIMITS,
    REPO_TASK,
    REWRITTEN,
    _Base as _ObserveBase,
    _Fixed,
)
from test_schemas import SchemaAssertions, load

ANSWER = (
    "# Svar\n\n" + "Ett svar långt nog för substanskravet. " * 12
    + "\n\n## Recommendation\nX.\n\n## Next step\nY.\n\n## Confidence\nHög.\n"
)


class _Recording:
    """A sink that keeps what it was given, so a test can read the log without
    touching a filesystem."""

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def write(self, record: Any) -> None:
        self.records.append(dict(record))


class TestTheThreeStatesOfACall(unittest.TestCase):
    """The distinction the whole design exists for."""

    def setUp(self):
        self.log = EventLog("run-1")

    def test_a_call_that_never_began_is_not_in_the_result(self):
        self.log.append("run_started")

        self.assertEqual(call_states(self.log), {})

    def test_a_call_with_no_recorded_outcome_is_unknown(self):
        """Not failed, and not absent. A crash between issuing a request and
        receiving the answer leaves a call that may already have had every
        effect it was going to have."""
        call = self.log.start_call("tool_call", target="read_file")

        self.assertEqual(call_states(self.log), {call: "unknown"})
        self.assertEqual(unfinished_calls(self.log), [call])

    def test_a_finished_call_reports_what_it_was(self):
        for outcome in CALL_OUTCOMES:
            with self.subTest(outcome=outcome):
                log = EventLog("run-1")
                call = log.start_call("tool_call", target="read_file")
                log.finish_call(call, outcome)

                self.assertEqual(call_states(log)[call], outcome)
                self.assertEqual(unfinished_calls(log), [])

    def test_unknown_is_not_an_outcome_anything_can_report(self):
        """It is the absence of a report, and a writer that could *state* it
        would make the two indistinguishable."""
        call = self.log.start_call("model_call")

        with self.assertRaises(ValueError):
            self.log.finish_call(call, "unknown")

    def test_one_unfinished_call_among_finished_ones_is_found(self):
        first = self.log.start_call("tool_call", target="a")
        self.log.finish_call(first, "ok")
        second = self.log.start_call("tool_call", target="b")
        third = self.log.start_call("tool_call", target="c")
        self.log.finish_call(third, "denied")

        self.assertEqual(unfinished_calls(self.log), [second])


class TestItOnlyEverAppends(unittest.TestCase):
    def setUp(self):
        self.log = EventLog("run-1")

    def test_the_log_assigns_the_position_and_not_the_caller(self):
        """A caller that could choose its sequence could write an event before
        one already recorded, which is the one thing append-only promises
        cannot happen."""
        for _ in range(3):
            self.log.append("run_started")

        self.assertEqual([event.sequence for event in self.log], [0, 1, 2])

    def test_there_is_no_way_to_change_or_remove_an_event(self):
        """Structural. A test that calls every method proves the paths it
        thought of; this says there are no others."""
        for forbidden in ("update", "replace", "remove", "delete", "pop", "clear",
                          "insert", "__setitem__"):
            with self.subTest(method=forbidden):
                self.assertFalse(hasattr(self.log, forbidden))

    def test_what_a_reader_gets_cannot_be_appended_through(self):
        self.log.append("run_started")

        self.assertIsInstance(self.log.events(), tuple)

    def test_an_event_cannot_be_edited_after_the_fact(self):
        event = self.log.append("run_started")

        with self.assertRaises(Exception):
            event.kind = "run_stopped"  # type: ignore[misc]

    def test_a_second_outcome_for_one_call_is_refused(self):
        call = self.log.start_call("tool_call", target="a")
        self.log.finish_call(call, "ok")

        with self.assertRaises(AppendOnlyViolation):
            self.log.finish_call(call, "failed")

    def test_an_outcome_for_a_call_that_never_started_is_refused(self):
        """It would be a record of something that did not happen."""
        with self.assertRaises(AppendOnlyViolation):
            self.log.finish_call("run-1:99", "ok")

    def test_an_observation_recorded_twice_is_two_records(self):
        """The rule `Observation` enforces by being frozen, applied over time.
        A source that changed under a run is something the log shows rather
        than something it hides."""
        self.log.append("observation_recorded", source_ids=["README.md"], digests=["a" * 64])
        self.log.append("observation_recorded", source_ids=["README.md"], digests=["b" * 64])

        recorded = [
            event.payload["digests"][0]
            for event in self.log
            if event.kind == "observation_recorded"
        ]
        self.assertEqual(recorded, ["a" * 64, "b" * 64])


class TestAnEventSaysWhatItIs(SchemaAssertions):
    def test_every_emitted_event_matches_the_schema(self):
        schema = load("atlas-event.v1.json")
        sink = _Recording()
        AtlasController(
            max_iterations=1, model_adapter=StubModelAdapter(ANSWER), events=sink
        ).run("granska repo atlas-core", json_mode=True)

        self.assertTrue(sink.records)
        for record in sink.records:
            with self.subTest(kind=record["kind"]):
                self.assert_matches(schema, record, "atlas-event.v1")

    def test_a_kind_outside_the_vocabulary_is_refused(self):
        with self.assertRaises(ValueError):
            EventLog("run-1").append("whatever_happened")

    def test_only_a_call_event_names_a_call(self):
        """So an unpaired call is visible rather than merely likely."""
        log = EventLog("run-1")
        with self.assertRaises(ValueError):
            Event(run_id="r", sequence=0, kind="run_started",
                  recorded_at="now", call_id="r:0")
        with self.assertRaises(ValueError):
            Event(run_id="r", sequence=0, kind="call_started", recorded_at="now")
        self.assertTrue(log.append("run_started").call_id is None)

    def test_every_kind_in_the_vocabulary_is_declared_in_the_schema(self):
        schema = load("atlas-event.v1.json")

        self.assertEqual(
            sorted(EVENT_KINDS), sorted(schema["properties"]["kind"]["enum"])
        )


class TestItSurvivesBeingWrittenDown(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = Path(self.tmp) / "nested" / "events.jsonl"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, task: str = "granska repo atlas-core") -> Any:
        return AtlasController(
            max_iterations=1, events=JsonlSink(self.path)
        ).run(task, json_mode=True)

    def test_one_json_object_per_line(self):
        self._run()

        lines = self.path.read_text(encoding="utf-8").splitlines()
        self.assertTrue(lines)
        for line in lines:
            json.loads(line)

    def test_a_second_run_appends_and_does_not_rewrite_the_first(self):
        first = self._run()
        before = self.path.read_text(encoding="utf-8")
        second = self._run()
        after = self.path.read_text(encoding="utf-8")

        self.assertTrue(after.startswith(before))
        runs = {record["run_id"] for record in read_jsonl(self.path)}
        self.assertEqual(runs, {first["run_id"], second["run_id"]})

    def test_a_torn_last_line_is_dropped_and_the_rest_stands(self):
        """What a crash during a write leaves behind. The events before it are
        still true, and the record that was never completed never happened."""
        self._run()
        whole = read_jsonl(self.path)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write('{"schema": "atlas-event.v1", "sequen')

        self.assertEqual(read_jsonl(self.path), whole)

    def test_a_crash_between_start_and_finish_reads_as_unknown(self):
        """The case the whole design is for, through the real file. The finish
        record is the torn one, so what survives is a started call with no
        outcome."""
        log = EventLog("run-1", JsonlSink(self.path))
        call = log.start_call("model_call", target="ollama")
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write('{"kind": "call_finished", "call_id": "run-1:0", "pay')

        records = read_jsonl(self.path)
        self.assertEqual(call_states(records), {call: "unknown"})
        self.assertEqual(unfinished_calls(records), [call])

    def test_corruption_anywhere_else_is_not_silently_dropped(self):
        """A torn last line is interruption. A bad line in the middle is
        corruption, and reading past it would report a log that never existed."""
        self._run()
        lines = self.path.read_text(encoding="utf-8").splitlines(keepends=True)
        lines.insert(1, "{ not json at all\n")
        self.path.write_text("".join(lines), encoding="utf-8")

        with self.assertRaises(json.JSONDecodeError):
            read_jsonl(self.path)

    def test_a_complete_but_invalid_last_line_is_corruption_and_raises(self):
        """Found in review. Only an *incomplete* last line is tolerated. One
        that ends with a newline was written in full, so if it does not parse
        the file is damaged — and shrugging at damage wherever it happens to
        sit would report a log that never existed."""
        self._run()
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write("{ not json at all\n")

        with self.assertRaises(json.JSONDecodeError):
            read_jsonl(self.path)

    def test_appending_after_a_torn_tail_is_refused(self):
        """Found in review, and the reason reading and appending cannot make
        the same allowance. The next whole object would be concatenated onto
        the fragment, turning it into one invalid line in the *middle* of the
        file — corruption rather than interruption, taking every following
        event down with it."""
        self._run()
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write('{"kind": "call_finished", "call_id": "x", "pay')

        with self.assertRaises(TornLogTail):
            JsonlSink(self.path)

    def test_the_refusal_happens_where_the_destination_is_chosen(self):
        """Not on the write that would do the damage. A run that discovered it
        halfway through would already have written events into a file it was
        damaging."""
        self._run()
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write("{ half a record")
        before = self.path.read_bytes()

        with self.assertRaises(TornLogTail):
            JsonlSink(self.path)

        self.assertEqual(self.path.read_bytes(), before)

    def test_dropping_the_fragment_is_explicit_and_leaves_the_rest_readable(self):
        """The only operation that makes the file consistent with how reading
        already treats the fragment — and it takes saying so."""
        self._run()
        whole = read_jsonl(self.path)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write('{"kind": "call_finished", "pay')

        log = EventLog("later-run", JsonlSink(self.path, truncate_torn_tail=True))
        log.append("run_started")

        records = read_jsonl(self.path)
        self.assertEqual(records[:-1], whole)
        self.assertEqual(records[-1]["run_id"], "later-run")

    def test_truncating_removes_only_what_follows_the_last_newline(self):
        """A record that was never completed, and nothing else."""
        self._run()
        whole = self.path.read_bytes()
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write('{"kind": "run_stop')

        JsonlSink(self.path, truncate_torn_tail=True)

        self.assertEqual(self.path.read_bytes(), whole)

    def test_a_clean_file_is_not_touched_and_a_new_one_is_fine(self):
        """The positive control: the check must not make ordinary use fail."""
        self._run()
        before = self.path.read_bytes()

        JsonlSink(self.path)
        JsonlSink(Path(self.tmp) / "fresh" / "new.jsonl")

        self.assertEqual(self.path.read_bytes(), before)


class TestWhatIsWrittenIsMasked(unittest.TestCase):
    """The run document is redacted on the way out because a source's bytes
    reach it through several channels. A durable log is another channel, and one
    that persists whether or not anyone exports the run."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = Path(self.tmp) / "events.jsonl"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_credential_in_a_payload_does_not_reach_the_file(self):
        secret = "AKIAIOSFODNN7EXAMPLE"
        log = EventLog("run-1", JsonlSink(self.path))

        log.append("observation_recorded", excerpt=f"aws_key = {secret}")

        self.assertNotIn(secret, self.path.read_text(encoding="utf-8"))

    def test_the_task_reaches_the_log_as_a_digest_and_not_as_text(self):
        """Even masked, the task is prose a run does not need to persist. The
        digest answers the only question the log has about it: whether two runs
        were given the same one."""
        AtlasController(max_iterations=1, events=JsonlSink(self.path)).run(
            "granska hemligheten i repot", json_mode=True
        )

        text = self.path.read_text(encoding="utf-8")
        self.assertNotIn("granska hemligheten", text)
        self.assertIn(digest("granska hemligheten i repot"), text)


class TestTheLoopRecordsWhatItDid(unittest.TestCase):
    def _sink(self) -> _Recording:
        return _Recording()

    def _kinds(self, records: list[dict[str, Any]]) -> list[str]:
        return [record["kind"] for record in records]

    def test_a_plain_run_records_start_plan_decision_and_stop(self):
        sink = self._sink()
        run = AtlasController(max_iterations=1, events=sink).run(
            "granska repo atlas-core", json_mode=True
        )

        self.assertEqual(
            self._kinds(sink.records),
            ["run_started", "plan_selected", "decision_recorded", "run_stopped"],
        )
        self.assertEqual(sink.records[-1]["payload"]["stop_reason"], run["stop_reason"])
        self.assertTrue(all(r["run_id"] == run["run_id"] for r in sink.records))

    def test_a_model_call_is_a_started_and_a_finished_event(self):
        sink = self._sink()
        AtlasController(
            max_iterations=1, model_adapter=StubModelAdapter(ANSWER), events=sink
        ).run("hej", json_mode=True)

        self.assertIn("call_started", self._kinds(sink.records))
        self.assertEqual(
            list(call_states(sink.records).values()), ["ok"]
        )

    def test_a_provider_that_fails_leaves_no_unfinished_call(self):
        """A failure this code saw and understood is recorded as one. Leaving it
        unfinished would put noise in the signal that has to stay trustworthy."""
        class Boom:
            def execute(self, **kwargs: Any) -> ModelResult:
                raise RuntimeError("nope")

        sink = self._sink()
        run = AtlasController(max_iterations=1, model_adapter=Boom(), events=sink).run(
            "hej", json_mode=True
        )

        self.assertEqual(run["stop_reason"], "tool_error")
        self.assertEqual(unfinished_calls(sink.records), [])
        self.assertEqual(list(call_states(sink.records).values()), ["failed"])

    def test_a_denied_tool_call_is_a_call_that_happened_and_was_refused(self):
        """Not one that never occurred. A reader of the log needs to see the
        attempt — that is most of what a log of a boundary is for."""
        def handler(ctx: Any, args: dict[str, Any]) -> str:
            return "done"

        tools = {
            "write_file": ToolDefinition(
                name="write_file", capability="write", handler=handler
            )
        }

        class Caller:
            def execute(self, **kwargs: Any) -> ModelResult:
                try:
                    kwargs["tools"].invoke("write_file", {})
                except Exception:
                    pass
                try:
                    kwargs["tools"].invoke("never_registered", {})
                except Exception:
                    pass
                return ModelResult(
                    output=ANSWER, provider="x", model="y",
                    metadata={"usage_tokens": "5"},
                )

        sink = self._sink()
        AtlasController(
            max_iterations=1, model_adapter=Caller(), tools=tools, events=sink
        ).run(
            "hej", json_mode=True,
            limits=RunLimits(
                wall_seconds=10, model_calls=2, tool_calls=4,
                tokens=100, output_bytes=10_000,
            ),
        )

        outcomes = sorted(call_states(sink.records).values())
        self.assertEqual(outcomes, ["denied", "denied", "ok"])
        self.assertEqual(unfinished_calls(sink.records), [])
        reasons = [
            record["payload"]["error"]
            for record in sink.records
            if record["kind"] == "call_finished"
            and record["payload"]["outcome"] == "denied"
        ]
        self.assertIn("tool not registered", reasons)
        self.assertIn("capability not allowed in read-only run", reasons)

    def test_an_input_reaches_the_log_as_a_digest_and_never_as_itself(self):
        sink = self._sink()
        AtlasController(
            max_iterations=1, model_adapter=StubModelAdapter(ANSWER), events=sink
        ).run("hej", json_mode=True)

        started = [r for r in sink.records if r["kind"] == "call_started"][0]
        self.assertEqual(started["payload"]["input_sha256"], digest("hej"))


class TestTheObservationPathIsRecorded(_ObserveBase):
    """The host reading again, which is the one path a log has to get right for
    the resume work: it is where bytes change under a run.

    This class exists because the first version of the observation event read a
    field `ObservationRound` does not have. Every test in this file passed —
    none of them configured an observer — and mypy and pyright caught it
    instead. A run with both an observer and a log would have raised
    `AttributeError` in the middle of the loop. The tests were the gap, so this
    is the test, built on the fixture that already drives that path.
    """

    def _run_with_log(self, sink: _Recording) -> Any:
        return AtlasController(
            max_iterations=2, model_adapter=_Fixed(self._stale_output()), events=sink
        ).run(
            REPO_TASK,
            evidence=self.base,
            json_mode=True,
            limits=LIMITS,
            observer=self.host,
        )

    def test_a_round_that_reads_again_is_recorded(self):
        (self.root / "README.md").write_text(REWRITTEN, encoding="utf-8")
        sink = _Recording()

        self._run_with_log(sink)

        rounds = [r for r in sink.records if r["kind"] == "observation_recorded"]
        self.assertTrue(rounds, "the observer path recorded nothing")
        self.assertTrue(rounds[0]["payload"]["has_new_material"])

    def test_a_source_that_changed_keeps_both_digests(self):
        """The rule that historical observations are not overwritten. A
        supersession says which bytes a claim was graded against, not merely
        that the source moved — and both readings stay in the log."""
        (self.root / "README.md").write_text(REWRITTEN, encoding="utf-8")
        sink = _Recording()

        self._run_with_log(sink)

        superseded = [
            item
            for record in sink.records
            if record["kind"] == "observation_recorded"
            for item in record["payload"]["superseded"]
        ]
        self.assertTrue(superseded, "no supersession was recorded")
        for item in superseded:
            with self.subTest(source=item["source_id"]):
                self.assertEqual(
                    item["previous_sha256"], self.observation.content_sha256
                )
                self.assertNotEqual(
                    item["new_sha256"], self.observation.content_sha256
                )

    def test_the_payload_names_fields_the_round_actually_has(self):
        """The regression itself, stated as a fact rather than as an absence of
        crashes: every key here is read off `ObservationRound`."""
        (self.root / "README.md").write_text(REWRITTEN, encoding="utf-8")
        sink = _Recording()

        self._run_with_log(sink)

        payload = [
            r for r in sink.records if r["kind"] == "observation_recorded"
        ][0]["payload"]
        self.assertEqual(
            sorted(payload),
            ["added", "has_new_material", "patterns", "requested", "superseded",
             "unchanged"],
        )


class TestTheObserverCallIsAlsoACall(_ObserveBase):
    """Found in review: `observer.observe()` ran with no `call_started`.

    That is the one path where bytes change under a run, and it was the one
    path the log could not speak about. An interruption during the read left no
    record at all, so the log said the call never began — the single reading the
    two-event design exists to make impossible.
    """

    def _run_with_log(self, sink: _Recording, observer: Any) -> Any:
        return AtlasController(
            max_iterations=2, model_adapter=_Fixed(self._stale_output()), events=sink
        ).run(
            REPO_TASK, evidence=self.base, json_mode=True,
            limits=LIMITS, observer=observer,
        )

    def _observe_calls(self, sink: _Recording) -> list[dict[str, Any]]:
        return [
            record
            for record in sink.records
            if record["kind"] == "call_started"
            and record["payload"]["call_kind"] == "observe"
        ]

    def test_a_read_is_a_started_and_a_finished_call(self):
        (self.root / "README.md").write_text(REWRITTEN, encoding="utf-8")
        sink = _Recording()

        self._run_with_log(sink, self.host)

        self.assertTrue(self._observe_calls(sink), "the read was not recorded")
        self.assertIn("ok", call_states(sink.records).values())
        self.assertEqual(unfinished_calls(sink.records), [])

    def test_a_host_that_raises_leaves_a_started_call_marked_failed(self):
        """Not an absent one. The host was asked, and the request may have had
        every effect it was going to have before it failed."""
        (self.root / "README.md").write_text(REWRITTEN, encoding="utf-8")
        sink = _Recording()

        class Exploding:
            def observe(self, request: Any) -> Any:
                raise RuntimeError("host is down")

        run = self._run_with_log(sink, Exploding())

        self.assertEqual(run["stop_reason"], "tool_error")
        started = self._observe_calls(sink)
        self.assertTrue(started, "an interrupted read must still say it began")
        self.assertEqual(
            call_states(sink.records)[started[0]["call_id"]], "failed"
        )

    def test_an_interrupted_read_reads_as_unknown_not_as_absent(self):
        """The crash case, through the log rather than through the loop: the
        read began and nothing recorded how it ended."""
        log = EventLog("run-1")
        call = log.start_call("observe", target="README.md")

        self.assertEqual(call_states(log), {call: "unknown"})

    def test_the_read_carries_what_was_asked_for_as_a_digest(self):
        (self.root / "README.md").write_text(REWRITTEN, encoding="utf-8")
        sink = _Recording()

        self._run_with_log(sink, self.host)

        started = self._observe_calls(sink)[0]
        self.assertEqual(started["payload"]["input_sha256"], digest(["README.md"]))
        self.assertEqual(started["payload"]["target"], "README.md")


class TestAccountingIsNotPartOfTheCall(unittest.TestCase):
    """Found in review, and a regression this branch introduced.

    `finish_call(ok)` ran as soon as the provider returned a usable reply, and
    the exception handler below then tried `finish_call(failed)` for the same
    id when the *budget* rejected the run. The log refused the second outcome,
    correctly — and that refusal replaced the budget error it was reporting and
    escaped `run()` entirely. Turning the log on changed what a run does, which
    is the one thing a log must never do.

    Charging tokens is accounting *about* a call, not part of it, and it can
    fail on a reply the provider delivered perfectly well.
    """

    def _adapter(self, metadata: dict[str, str]) -> Any:
        class Producer:
            def execute(self, **kwargs: Any) -> ModelResult:
                return ModelResult(
                    output=ANSWER, provider="p", model="m", metadata=dict(metadata)
                )

        return Producer()

    def _limits(self) -> RunLimits:
        return RunLimits(
            wall_seconds=10, model_calls=2, tool_calls=0,
            tokens=100, output_bytes=10_000,
        )

    def _run(self, metadata: dict[str, str], sink: Any = None) -> Any:
        return AtlasController(
            max_iterations=1, model_adapter=self._adapter(metadata), events=sink
        ).run("hej", json_mode=True, limits=self._limits())

    def test_a_provider_that_reports_no_usage_still_stops_the_normal_way(self):
        sink = _Recording()

        run = self._run({}, sink)

        self.assertEqual(run["stop_reason"], "tool_error")
        self.assertEqual(run["metadata"]["failure"]["error"], "UnmeteredUsage")

    def test_a_run_over_its_token_budget_still_stops_the_normal_way(self):
        sink = _Recording()

        run = self._run({"usage_tokens": "9999"}, sink)

        self.assertEqual(run["stop_reason"], "budget_exhausted")

    def test_the_call_is_finished_once_and_the_run_still_records_its_stop(self):
        """The two facts the double finish destroyed: one outcome per call, and
        a `run_stopped` event at the end."""
        for metadata in ({}, {"usage_tokens": "9999"}):
            with self.subTest(metadata=metadata):
                sink = _Recording()

                self._run(metadata, sink)

                kinds = [record["kind"] for record in sink.records]
                self.assertEqual(kinds.count("call_finished"), 1)
                self.assertEqual(kinds[-1], "run_stopped")
                self.assertEqual(unfinished_calls(sink.records), [])

    def test_the_outcome_recorded_is_the_providers_and_not_the_budgets(self):
        """The call succeeded. What failed was the accounting after it, and the
        run document is where that belongs."""
        sink = _Recording()

        self._run({}, sink)

        finished = [r for r in sink.records if r["kind"] == "call_finished"][0]
        self.assertEqual(finished["payload"]["outcome"], "ok")

    def test_a_budgeted_run_behaves_the_same_with_and_without_a_log(self):
        """The property the regression broke, tested where it broke it: with a
        budget. The earlier version of this assertion used an unbudgeted run
        and could not have caught it."""
        for metadata in ({}, {"usage_tokens": "9999"}):
            with self.subTest(metadata=metadata):
                without = _comparable(self._run(metadata))
                with_log = _comparable(self._run(metadata, _Recording()))

                self.assertEqual(without, with_log)


def _comparable(document: dict[str, Any]) -> dict[str, Any]:
    """A run document with the parts that differ between any two runs removed.

    The id, the timestamp and the budget's monotonic deadline are different on
    every run whatever else is true, so leaving them in would make "the same
    with and without a log" impossible to state rather than merely false.
    """
    document.pop("run_id", None)
    document.pop("created_at", None)
    usage = document.get("metadata", {}).get("budget_usage")
    if isinstance(usage, dict):
        usage.pop("deadline_monotonic", None)
    return document


class TestALogChangesNothingAboutTheRun(unittest.TestCase):
    """It records; it decides nothing. Asserted because a log that altered a run
    would make every measurement taken with one unusable."""

    def _document(self, **kwargs: Any) -> dict[str, Any]:
        return _comparable(
            AtlasController(max_iterations=2, **kwargs).run(
                "granska repo atlas-core", json_mode=True
            )
        )

    def test_the_document_is_the_same_with_and_without_one(self):
        self.assertEqual(self._document(), self._document(events=_Recording()))

    def test_no_sink_means_no_log_and_no_cost(self):
        controller = AtlasController(max_iterations=1)

        self.assertIsNone(controller.events)


if __name__ == "__main__":
    unittest.main()
