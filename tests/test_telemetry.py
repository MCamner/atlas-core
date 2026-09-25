"""v1.5 telemetry: `atlas metrics` reads event logs into `atlas-metrics.v1`.

The negative case is the point: a log full of task text, a credential, paths
and a user name yields metrics holding none of them, because the output is
built from an allowlist.
"""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
from typing import Any
import unittest

from atlas_core.adapters.model import ModelResult
from atlas_core.approval import ApprovalAuthority, Operation
from atlas_core.claim_check import ClaimKind, TypedClaim
from atlas_core.cli import main
from atlas_core.eventlog import EventLog, JsonlSink
from atlas_core.machine import STOP_REASONS
from atlas_core.telemetry import STOP_CLASSES, metrics, run_metrics
import test_repo_path_evidence as evidence_tests
from test_schemas import load

HEAD = "a" * 40


class _TwoClaims(evidence_tests._Producer):
    """One claim the source holds and one it refutes."""

    def execute(self, **kwargs: Any) -> ModelResult:
        self.calls += 1
        settings = [o for o in self.host.read if o.path == "settings.env"]
        findings = []
        if settings:
            held = evidence_tests._WRITER._finding(settings[-1], "PASSWORD=admin")
            # The same cited source, typed as lacking what it contains.
            source = settings[-1]
            refuted = dict(held, claim=TypedClaim(
                kind=ClaimKind.LACKS, source_id=source.source_id, text="PASSWORD=admin",
            ).render(source.path, source.line_start, source.line_end), typed_claim={
                "kind": ClaimKind.LACKS.value, "source_id": source.source_id,
                "text": "PASSWORD=admin",
            })
            findings = [held, refuted]
        output = evidence_tests._WRITER._output(findings, [o.path for o in settings])
        return ModelResult(output=output, provider="test", model="producer",
                           metadata={"usage_tokens": "7"})


def strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for k, v in value.items() for s in [k, *strings(v)]]
    if isinstance(value, list):
        return [s for item in value for s in strings(item)]
    return []


class TestFromARealRun(evidence_tests._Repo):
    def setUp(self) -> None:
        super().setUp()
        host = evidence_tests._Recording(self.root)
        self.result = self._run(host, _TwoClaims(host))
        self.report = metrics([self.log])

    def test_the_log_carries_usage_and_verdict_counts(self) -> None:
        stopped = self._events("run_stopped")[0]["payload"]
        self.assertEqual(set(stopped["usage"]),
                         {"model_calls", "tool_calls", "tokens", "output_bytes"})
        self.assertGreaterEqual(stopped["usage"]["tokens"], 7)
        decided = self._events("decision_recorded")[0]["payload"]["citation_verdicts"]
        self.assertEqual(sorted(decided), sorted({
            check["verdict"] for check in self.result["evaluations"][0]["citation_checks"]}))

    def test_metrics_count_what_the_run_did(self) -> None:
        (run,) = self.report["runs"]
        self.assertEqual(run["run_id"], self.result["run_id"])
        self.assertTrue(run["finished"])
        self.assertEqual(run["stop_reason"], self.result["stop_reason"])
        self.assertEqual(run["iterations"], self.result["iteration"])
        self.assertEqual(run["usage"]["tokens"], self.result["metadata"]["budget_usage"]["tokens"])
        claims = run["claims"]
        checks = [c for e in self.result["evaluations"] for c in e["citation_checks"]]
        self.assertEqual(claims["checked"], len(checks))
        self.assertEqual(claims["verified"], sum(c["verdict"] == "verified" for c in checks))
        self.assertEqual(claims["contradicted"],
                         sum(c["verdict"] == "contradicted" for c in checks))
        self.assertGreater(claims["verified"], 0)
        self.assertGreater(claims["contradicted"], 0)
        self.assertEqual(claims["verification_rate"],
                         round(claims["verified"] / claims["checked"], 4))
        self.assertGreater(run["calls"]["model_call"]["ok"], 0)
        self.assertIsNotNone(run["latency_seconds"])

    def test_the_document_matches_its_schema(self) -> None:
        schema = load("atlas-metrics.v1.json")
        self.assertEqual(self.report["schema"], schema["properties"]["schema"]["const"])
        self.assertEqual(set(self.report), set(schema["required"]))
        run_schema = schema["properties"]["runs"]["items"]
        self.assertEqual(set(self.report["runs"][0]), set(run_schema["required"]))
        self.assertEqual(set(self.report["totals"]),
                         set(schema["properties"]["totals"]["required"]))


class TestNothingSensitiveLeaves(evidence_tests._Repo):
    def test_only_numbers_vocabularies_and_run_ids(self) -> None:
        host = evidence_tests._Recording(self.root)
        self._run(host, _TwoClaims(host))
        audit = self.tmp / "audit.jsonl"
        approvals = ApprovalAuthority(log=EventLog("audit-mattias.camner", JsonlSink(audit)),
                                      head_of=lambda _r: HEAD)
        op = Operation(kind="ref", tool="create_branch",
                       arguments={"token": evidence_tests.TOKEN}, repo=str(self.root),
                       ref="refs/heads/atlas/x", head=HEAD)
        approvals.refuse(approvals.request(op), refused_by="mattias.camner")
        report = metrics([self.log, audit])
        text = json.dumps(report)
        for secret in (evidence_tests.TOKEN, evidence_tests.TASK, "mattias", str(self.root),
                       str(self.tmp), "PASSWORD", "settings.env", "create_branch", op.sha256):
            self.assertNotIn(secret, text)
        run_ids = {run["run_id"] for run in report["runs"]}
        vocabulary = (set(STOP_REASONS) | set(STOP_CLASSES) | run_ids
                      | {"atlas-metrics.v1", "run", "audit"})
        keys = {"schema", "runs", "totals"}
        values = [s for s in strings(report) if s not in vocabulary]
        allowed_keys = set(load("atlas-metrics.v1.json")["properties"]["totals"]["required"])
        for run in report["runs"]:
            allowed_keys |= set(run) | set(run["claims"]) | set(run["approvals"])
            allowed_keys |= set(run["writes"]) | set(run["usage"] or {}) | set(run["calls"])
            for counts in run["calls"].values():
                allowed_keys |= set(counts)
        self.assertEqual([v for v in values if v not in allowed_keys | keys], [])
        self.assertEqual(report["totals"]["user_refusals"], 1)
        self.assertEqual(report["totals"]["audit_logs"], 1)


def record(kind: str, sequence: int, payload: dict[str, Any] | None = None,
           call_id: str | None = None, iteration: int = 0) -> dict[str, Any]:
    return {"run_id": "r", "sequence": sequence, "kind": kind, "iteration": iteration,
            "recorded_at": f"2026-09-25T10:00:{sequence:02d}+00:00", "call_id": call_id,
            "payload": payload or {}}


class TestCounting(unittest.TestCase):
    def test_calls_by_outcome_including_unfinished(self) -> None:
        records = [
            record("run_started", 0),
            record("call_started", 1, {"call_kind": "tool_call"}, "c1"),
            record("call_finished", 2, {"outcome": "denied"}, "c1"),
            record("call_started", 3, {"call_kind": "tool_call"}, "c2"),
            record("call_finished", 4, {"outcome": "failed"}, "c2"),
            record("call_started", 5, {"call_kind": "model_call"}, "c3"),
            record("run_stopped", 9, {"stop_reason": "tool_error", "stop_class": "runtime"},
                   iteration=1),
        ]
        run = run_metrics(records)
        self.assertEqual(run["calls"]["tool_call"],
                         {"ok": 0, "denied": 1, "failed": 1, "unfinished": 0})
        self.assertEqual(run["calls"]["model_call"]["unfinished"], 1)
        self.assertEqual(run["tool_errors"], 2)
        self.assertEqual(run["latency_seconds"], 9.0)
        self.assertEqual(run["iterations"], 1)
        self.assertIsNone(run["usage"])

    def test_tool_errors_are_tool_calls_only(self) -> None:
        records = [
            record("run_started", 0),
            record("call_started", 1, {"call_kind": "model_call"}, "m"),
            record("call_finished", 2, {"outcome": "failed"}, "m"),
            record("call_started", 3, {"call_kind": "observe"}, "o"),
            record("call_finished", 4, {"outcome": "denied"}, "o"),
            record("run_stopped", 5, {"stop_reason": "tool_error"}),
        ]
        run = run_metrics(records)
        self.assertEqual(run["tool_errors"], 0)
        self.assertEqual(run["calls"]["model_call"]["failed"], 1)
        self.assertEqual(run["calls"]["observe"]["denied"], 1)

    def test_a_host_chosen_run_id_is_shown_as_a_digest(self) -> None:
        issued = "5f0c8e8a-3b1d-4c55-9a6e-2f1f0d3c9b7a"
        chosen = "mattias.camner-ghp_secret"
        self.assertEqual(run_metrics([{**record("run_started", 0), "run_id": issued}])["run_id"],
                         issued)
        shown = run_metrics([{**record("run_started", 0), "run_id": chosen}])["run_id"]
        self.assertRegex(shown, r"^sha256:[0-9a-f]{16}$")
        self.assertNotIn("mattias", shown)

    def test_values_outside_the_vocabularies_are_not_counted(self) -> None:
        records = [
            record("run_started", 0),
            record("decision_recorded", 1, {"citation_verdicts": {
                "verified": 2, "made_up": 5, "contradicted": -1, "insufficient_evidence": "3",
            }}),
            record("run_stopped", 2, {"stop_reason": "sk-live-secret", "stop_class": "whatever",
                                      "usage": {"tokens": "lots", "tool_calls": 3}}),
        ]
        run = run_metrics(records)
        self.assertEqual(run["claims"]["checked"], 2)
        self.assertEqual(run["claims"]["verification_rate"], 1.0)
        self.assertIsNone(run["stop_reason"])
        self.assertIsNone(run["stop_class"])
        self.assertEqual(run["usage"], {"model_calls": None, "tool_calls": 3, "tokens": None,
                                        "output_bytes": None})

    def test_an_unfinished_run_has_no_latency(self) -> None:
        run = run_metrics([record("run_started", 0), record("plan_selected", 1)])
        self.assertFalse(run["finished"])
        self.assertIsNone(run["latency_seconds"])


class TestCli(evidence_tests._Repo):
    def test_metrics_command(self) -> None:
        host = evidence_tests._Recording(self.root)
        self._run(host, _TwoClaims(host))
        out, err = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["metrics", "--event-log", str(self.log), "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue())["totals"]["runs"], 1)
        with redirect_stdout(StringIO()), redirect_stderr(err):
            code = main(["metrics", "--event-log", str(Path(self.tmp) / "missing.jsonl")])
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
