"""v1.5 feedback loop: confirmed outcome → candidate → gate → opt-in promotion.

Nothing is automatic and nothing is rewritten: a run's log and a recorded
candidate keep their bytes, promotion appends, and a candidate whose evidence
no longer matches its log is refused.
"""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
from typing import Any

from atlas_core.cli import main
from atlas_core.feedback import PromotionRefused, gate, promote, record_outcome
import test_repo_path_evidence as evidence_tests
from test_schemas import load


class _Feedback(evidence_tests._Repo):
    def setUp(self) -> None:
        super().setUp()
        host = evidence_tests._Recording(self.root)
        self.result = self._run(host, evidence_tests._Producer(host))
        self.run_id = str(self.result["run_id"])
        self.store = self.tmp / "store"
        self.log_bytes = self.log.read_bytes()

    def record(self, **overrides: Any) -> dict[str, Any]:
        fields: dict[str, Any] = {"outcome": "confirmed", "recorded_by": "mattias",
                                  "lesson": "settings.env should never hold a password"}
        fields.update(overrides)
        return record_outcome(self.store, self.log, self.run_id, **fields)

    def lines(self, name: str) -> list[dict[str, Any]]:
        path = self.store / name
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


class TestTheLoop(_Feedback):
    def test_a_confirmed_outcome_becomes_a_candidate_with_provenance(self) -> None:
        candidate = self.record()
        self.assertEqual(self.lines("candidates.jsonl"), [candidate])
        self.assertFalse((self.store / "learnings.jsonl").exists())
        provenance = candidate["provenance"]
        self.assertEqual(provenance["stop_reason"], self.result["stop_reason"])
        self.assertEqual(provenance["route"], self.result["route"]["name"])
        paths = {source["path"]: source["sha256"] for source in provenance["sources"]}
        self.assertEqual(paths["settings.env"],
                         evidence_tests._sha256(self.root / "settings.env"))
        self.assertEqual(self.log.read_bytes(), self.log_bytes)
        self.assertEqual(gate(candidate, self.log), [])

    def test_promotion_is_explicit_appends_once_and_rewrites_nothing(self) -> None:
        candidate = self.record()
        candidates_bytes = (self.store / "candidates.jsonl").read_bytes()
        learning = promote(self.store, candidate["candidate_id"], self.log, promoted_by="mattias")
        self.assertEqual(learning["candidate"], candidate)
        self.assertEqual(self.lines("learnings.jsonl"), [learning])
        self.assertEqual((self.store / "candidates.jsonl").read_bytes(), candidates_bytes)
        self.assertEqual(self.log.read_bytes(), self.log_bytes)
        with self.assertRaises(PromotionRefused) as caught:
            promote(self.store, candidate["candidate_id"], self.log, promoted_by="mattias")
        self.assertIn("already promoted", str(caught.exception))
        self.assertEqual(len(self.lines("learnings.jsonl")), 1)

    def test_a_rejected_outcome_is_a_candidate_too(self) -> None:
        candidate = self.record(outcome="rejected", lesson="the finding was not on topic")
        self.assertEqual(candidate["outcome"], "rejected")
        self.assertEqual(gate(candidate, self.log), [])

    def test_documents_match_their_schemas(self) -> None:
        candidate = self.record()
        learning = promote(self.store, candidate["candidate_id"], self.log, promoted_by="m")
        for schema_name, document in (("atlas-learning-candidate.v1.json", candidate),
                                      ("atlas-learning.v1.json", learning)):
            schema = load(schema_name)
            self.assert_matches(schema, document, schema_name)
        prov_schema = load("atlas-learning-candidate.v1.json")["properties"]["provenance"]
        self.assertEqual(set(candidate["provenance"]), set(prov_schema["required"]))

    def test_a_credential_in_a_lesson_is_masked(self) -> None:
        candidate = self.record(lesson=f"rotate {evidence_tests.TOKEN} now")
        self.assertNotIn(evidence_tests.TOKEN, json.dumps(candidate))
        self.assertNotIn(evidence_tests.TOKEN, (self.store / "candidates.jsonl").read_text())

    def test_a_run_never_writes_to_the_store(self) -> None:
        self.assertFalse(self.store.exists())


class TestTheGateRefuses(_Feedback):
    def test_a_changed_log(self) -> None:
        candidate = self.record()
        with self.log.open("a") as log:
            log.write(self.log.read_text().splitlines()[-1] + "\n")
        with self.assertRaises(PromotionRefused) as caught:
            promote(self.store, candidate["candidate_id"], self.log, promoted_by="m")
        self.assertIn("event log changed since the outcome was recorded", caught.exception.reasons)
        self.assertFalse((self.store / "learnings.jsonl").exists())

    def forge(self, **changes: Any) -> dict[str, Any]:
        candidate = self.record()
        forged = json.loads(json.dumps(candidate))
        for dotted, value in changes.items():
            target = forged
            *path, last = dotted.split(".")
            for key in path:
                target = target[key]
            target[last] = value
        forged["candidate_id"] = "f" * 32
        with (self.store / "candidates.jsonl").open("a") as store:
            store.write(json.dumps(forged) + "\n")
        return forged

    def test_forged_provenance(self) -> None:
        cases = {
            "provenance.stop_reason": "forged_stop",
            "provenance.task_sha256": "0" * 64,
            "provenance.route": "other",
            "provenance.sources": [],
        }
        for dotted, value in cases.items():
            with self.subTest(field=dotted):
                self.setUp()
                forged = self.forge(**{dotted: value})
                with self.assertRaises(PromotionRefused) as caught:
                    promote(self.store, forged["candidate_id"], self.log, promoted_by="m")
                self.assertIn(f"{dotted} does not match the event log", caught.exception.reasons)

    def test_forged_schema_and_vocabulary(self) -> None:
        for dotted, value in (("schema", "atlas-learning-candidate.v2"),
                              ("outcome", "probably"), ("lesson", "  "), ("provenance", None)):
            with self.subTest(field=dotted):
                self.setUp()
                forged = self.forge(**{dotted: value})
                with self.assertRaises(PromotionRefused):
                    promote(self.store, forged["candidate_id"], self.log, promoted_by="m")

    def test_unknown_and_duplicate_candidates(self) -> None:
        candidate = self.record()
        with self.assertRaises(PromotionRefused):
            promote(self.store, "0" * 32, self.log, promoted_by="m")
        with (self.store / "candidates.jsonl").open("a") as store:
            store.write(json.dumps(candidate) + "\n")
        with self.assertRaises(PromotionRefused) as caught:
            promote(self.store, candidate["candidate_id"], self.log, promoted_by="m")
        self.assertIn("more than once", str(caught.exception))

    def test_an_unfinished_run_has_no_outcome(self) -> None:
        lines = self.log.read_text().splitlines()
        unfinished = self.tmp / "unfinished.jsonl"
        unfinished.write_text("\n".join(l for l in lines if '"run_stopped"' not in l) + "\n")
        with self.assertRaises(ValueError):
            record_outcome(self.store, unfinished, self.run_id, outcome="confirmed",
                           lesson="x", recorded_by="m")

    def test_bad_input(self) -> None:
        for overrides in ({"outcome": "maybe"}, {"lesson": " "}, {"lesson": "x" * 2001},
                          {"recorded_by": ""}):
            with self.subTest(**{k: str(v)[:10] for k, v in overrides.items()}):
                with self.assertRaises(ValueError):
                    self.record(**overrides)
        with self.assertRaises(PromotionRefused):
            promote(self.store, "x", self.log, promoted_by=" ")


class TestCli(_Feedback):
    def cli(self, *args: str) -> tuple[int, str]:
        out = StringIO()
        with redirect_stdout(out), redirect_stderr(StringIO()):
            code = main(list(args))
        return code, out.getvalue()

    def test_record_then_promote(self) -> None:
        code, out = self.cli("feedback", "record", self.run_id, "--event-log", str(self.log),
                             "--outcome", "confirmed", "--lesson", "keep secrets out",
                             "--store", str(self.store))
        self.assertEqual(code, 0)
        candidate_id = json.loads(out)["candidate_id"]
        code, out = self.cli("feedback", "promote", candidate_id, "--event-log", str(self.log),
                             "--store", str(self.store))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["schema"], "atlas-learning.v1")
        code, _ = self.cli("feedback", "promote", candidate_id, "--event-log", str(self.log),
                           "--store", str(self.store))
        self.assertEqual(code, 2)
        self.assertEqual(Path(self.log).read_bytes(), self.log_bytes)
