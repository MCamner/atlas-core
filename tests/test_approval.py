"""Write approval: one person's yes, for one exact operation, spent once.

v1.5 exit gate, in Core's terms: a refused or expired approval gives zero
mutations, and a moved HEAD invalidates an approval.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from typing import Any

from atlas_core.approval import (
    MAX_TTL_SECONDS,
    ApprovalAuthority,
    ApprovalRejected,
    Operation,
    clean_head,
)
from atlas_core.budget import RunBudget, RunLimits
from atlas_core.eventlog import EventLog
from atlas_core.tool_gateway import ToolDefinition, ToolDenied, ToolGateway
from test_schemas import SchemaAssertions, load

HEAD = "a" * 40
MOVED = "b" * 40


class Clock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


class Repo:
    """What the fake write tool touches, and the state the authority probes."""

    def __init__(self) -> None:
        self.head = HEAD
        self.writes: list[dict[str, Any]] = []

    def head_of(self, repo: str) -> str:
        return self.head


def budget() -> RunBudget:
    return RunBudget(RunLimits(wall_seconds=10, model_calls=0, tool_calls=4,
                               tokens=0, output_bytes=10_000))


def setup(**authority: Any) -> tuple[ToolGateway, ApprovalAuthority, Repo, EventLog, Clock]:
    repo = Repo()
    clock = Clock()
    log = EventLog(run_id="run-1")

    def apply_patch(_ctx: Any, args: dict[str, Any]) -> dict[str, str]:
        repo.writes.append(dict(args))
        return {"branch": args["branch"]}

    def describe(args: dict[str, Any]) -> Operation:
        return Operation(kind="diff", tool="apply_patch", arguments=args,
                         repo="/repo", ref="main", head=repo.head)

    tool = ToolDefinition(
        "apply_patch", "write", apply_patch, describe=describe,
        input_schema={"type": "object", "required": ["branch", "diff"],
                      "additionalProperties": False,
                      "properties": {"branch": {"type": "string"},
                                     "diff": {"type": "string"}}},
    )
    approvals = ApprovalAuthority(log=log, head_of=repo.head_of, clock=clock, **authority)
    gate = ToolGateway(budget=budget(), tools={"apply_patch": tool}, log=log,
                       approvals=approvals)
    return gate, approvals, repo, log, clock


ARGS = {"branch": "atlas/fix-readme", "diff": "--- a/README.md\n+++ b/README.md\n"}


def operation(repo: Repo, args: dict[str, Any] = ARGS) -> Operation:
    return Operation(kind="diff", tool="apply_patch", arguments=args,
                     repo="/repo", ref="main", head=repo.head)


def decisions(log: EventLog) -> list[tuple[str, str | None]]:
    return [(e.payload["decision"], e.payload.get("reason"))
            for e in log.events() if e.kind == "approval_recorded"]


class TestApprovedWrite(unittest.TestCase):
    def test_a_granted_approval_runs_the_exact_write_once(self) -> None:
        gate, approvals, repo, log, _ = setup()
        approval_id = approvals.request(operation(repo))
        token = approvals.grant(approval_id, granted_by="mattias", ttl_seconds=600)

        self.assertEqual(gate.invoke_write("apply_patch", dict(ARGS), token=token),
                         {"branch": "atlas/fix-readme"})
        self.assertEqual(repo.writes, [ARGS])
        self.assertEqual(decisions(log), [("requested", None), ("granted", None),
                                          ("consumed", None)])
        finished = [e for e in log.events() if e.kind == "call_finished"]
        self.assertEqual([e.payload["outcome"] for e in finished], ["ok"])
        started = [e for e in log.events() if e.kind == "call_started"]
        self.assertEqual(started[0].payload["capability"], "write")

        with self.assertRaises(ApprovalRejected) as caught:
            gate.invoke_write("apply_patch", dict(ARGS), token=token)
        self.assertEqual(caught.exception.reason, "already_used")
        self.assertEqual(len(repo.writes), 1)

    def test_concurrent_use_of_one_token_writes_once(self) -> None:
        import threading

        gate, approvals, repo, _, _ = setup()
        token = approvals.grant(approvals.request(operation(repo)),
                                granted_by="mattias", ttl_seconds=60)
        outcomes: list[str] = []

        def attempt() -> None:
            try:
                gate.invoke_write("apply_patch", dict(ARGS), token=token)
                outcomes.append("ok")
            except ApprovalRejected as exc:
                outcomes.append(exc.reason)

        threads = [threading.Thread(target=attempt) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sorted(outcomes), ["already_used"] * 7 + ["ok"])
        self.assertEqual(len(repo.writes), 1)

    def test_the_token_is_never_written_down(self) -> None:
        gate, approvals, repo, log, _ = setup()
        token = approvals.grant(approvals.request(operation(repo)),
                                granted_by="mattias", ttl_seconds=60)
        gate.invoke_write("apply_patch", dict(ARGS), token=token)
        self.assertNotIn(token, json.dumps([e.to_dict() for e in log.events()]))


class TestZeroMutations(unittest.TestCase):
    """Each refusal happens before the handler: nothing is written."""

    def assert_refused(self, gate: ToolGateway, repo: Repo, token: str, reason: str,
                       args: dict[str, Any] = ARGS) -> None:
        with self.assertRaises(ApprovalRejected) as caught:
            gate.invoke_write("apply_patch", dict(args), token=token)
        self.assertEqual(caught.exception.reason, reason)
        self.assertEqual(repo.writes, [])
        self.assertEqual(gate.budget.tool_calls, 0)

    def test_refused(self) -> None:
        gate, approvals, repo, log, _ = setup()
        approval_id = approvals.request(operation(repo))
        approvals.refuse(approval_id, refused_by="mattias")
        with self.assertRaises(ValueError):
            approvals.grant(approval_id, granted_by="mattias", ttl_seconds=60)
        self.assert_refused(gate, repo, "no-token-was-issued", "unknown_token")
        self.assertEqual(decisions(log)[-1], ("rejected", "unknown_token"))

    def test_expired(self) -> None:
        gate, approvals, repo, log, clock = setup()
        token = approvals.grant(approvals.request(operation(repo)),
                                granted_by="mattias", ttl_seconds=60)
        clock.now += 60
        self.assert_refused(gate, repo, token, "expired")
        self.assertEqual(decisions(log)[-1], ("rejected", "expired"))

    def test_head_moved(self) -> None:
        gate, approvals, repo, log, _ = setup()
        token = approvals.grant(approvals.request(operation(repo)),
                                granted_by="mattias", ttl_seconds=60)
        repo.head = MOVED
        self.assert_refused(gate, repo, token, "head_moved")
        self.assertEqual(decisions(log)[-1], ("rejected", "head_moved"))

    def test_head_moved_between_request_and_write_of_the_same_operation(self) -> None:
        gate, approvals, repo, log, _ = setup()
        op = operation(repo)
        token = approvals.grant(approvals.request(op), granted_by="mattias", ttl_seconds=60)
        repo.head = MOVED
        with self.assertRaises(ApprovalRejected) as caught:
            approvals.consume(token, op)
        self.assertEqual(caught.exception.reason, "head_moved")
        self.assertEqual(decisions(log)[-1], ("rejected", "head_moved"))

    def test_other_arguments(self) -> None:
        gate, approvals, repo, _, _ = setup()
        token = approvals.grant(approvals.request(operation(repo)),
                                granted_by="mattias", ttl_seconds=60)
        self.assert_refused(gate, repo, token, "operation_mismatch",
                            {"branch": "main", "diff": ARGS["diff"]})
        # The token was not spent by the mismatch: the approved call still runs.
        gate.invoke_write("apply_patch", dict(ARGS), token=token)
        self.assertEqual(repo.writes, [ARGS])

    def test_unknown_token(self) -> None:
        gate, _, repo, _, _ = setup()
        self.assert_refused(gate, repo, "approved: true", "unknown_token")


class TestModelPath(unittest.TestCase):
    def test_invoke_never_runs_a_write_tool_even_with_a_valid_token(self) -> None:
        gate, approvals, repo, _, _ = setup()
        token = approvals.grant(approvals.request(operation(repo)),
                                granted_by="mattias", ttl_seconds=60)
        with self.assertRaises(ToolDenied):
            gate.invoke("apply_patch", {**ARGS, "token": token, "approved": True})
        self.assertEqual(repo.writes, [])

    def test_invoke_write_refuses_read_undescribed_and_unauthorised_tools(self) -> None:
        touched: list[str] = []
        read = ToolDefinition("read", "read", lambda _c, _a: touched.append("read"))
        bare = ToolDefinition("bare", "write", lambda _c, _a: touched.append("bare"))
        gate = ToolGateway(budget=budget(), tools={"read": read, "bare": bare},
                           approvals=ApprovalAuthority(head_of=lambda _r: HEAD))
        for name in ("read", "bare", "missing"):
            with self.subTest(name=name), self.assertRaises(ToolDenied):
                gate.invoke_write(name, {}, token="t")
        no_authority, _, repo, _, _ = setup()
        no_authority._approvals = None
        with self.assertRaises(ToolDenied):
            no_authority.invoke_write("apply_patch", dict(ARGS), token="t")
        self.assertEqual(touched, [])
        self.assertEqual(repo.writes, [])

    def test_a_write_tool_cannot_be_retried(self) -> None:
        with self.assertRaises(ValueError):
            ToolDefinition("w", "write", lambda _c, _a: None, idempotent=True, max_attempts=2)


class TestGrant(unittest.TestCase):
    def test_ttl_is_bounded_and_a_grant_names_who_gave_it(self) -> None:
        _, approvals, repo, _, _ = setup()
        approval_id = approvals.request(operation(repo))
        for ttl in (0, -1, MAX_TTL_SECONDS + 1):
            with self.subTest(ttl=ttl), self.assertRaises(ValueError):
                approvals.grant(approval_id, granted_by="mattias", ttl_seconds=ttl)
        with self.assertRaises(ValueError):
            approvals.grant(approval_id, granted_by=" ", ttl_seconds=60)

    def test_operation_needs_a_full_commit(self) -> None:
        for head in ("HEAD", "main", "unknown", "abc123"):
            with self.subTest(head=head), self.assertRaises(ValueError):
                Operation(kind="diff", tool="t", arguments={}, repo="/r", ref="main", head=head)


class TestRecords(SchemaAssertions):
    def test_approval_documents_match_the_schema(self) -> None:
        _, approvals, repo, log, _ = setup()
        schema = load("atlas-approval.v1.json")
        granted = approvals.request(operation(repo))
        approvals.grant(granted, granted_by="mattias", ttl_seconds=60)
        refused = approvals.request(operation(repo, {"branch": "x", "diff": ""}))
        approvals.refuse(refused, refused_by="mattias")
        pending = approvals.request(operation(repo, {"branch": "y", "diff": ""}))
        for approval_id, granted_value in ((granted, True), (refused, False), (pending, None)):
            doc = approvals.record(approval_id, run_id="run-1")
            self.assert_matches(schema, doc, approval_id)
            self.assertIs(doc["granted"], granted_value)
            self.assertEqual(doc["binds_to"] is not None, granted_value is True)
        self.assertEqual(approvals.record(granted, run_id="run-1")["binds_to"]["sha256"],
                         operation(repo).sha256)

    def test_approval_events_match_the_event_schema(self) -> None:
        _, approvals, repo, log, _ = setup()
        approvals.request(operation(repo))
        schema = load("atlas-event.v1.json")
        for event in log.events():
            self.assertIn(event.kind, schema["properties"]["kind"]["enum"])
            self.assert_matches(schema, event.to_dict(), event.kind)


class TestCleanHead(unittest.TestCase):
    def git(self, root: Path, *args: str) -> str:
        return subprocess.run(["git", "-C", str(root), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def test_a_real_repository(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.git(root, "init", "-q")
            (root / "README.md").write_text("one\n")
            self.git(root, "add", ".")
            self.git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "one")
            first = self.git(root, "rev-parse", "HEAD")
            self.assertEqual(clean_head(str(root)), first)

            (root / "README.md").write_text("edited\n")
            with self.assertRaises(ApprovalRejected) as caught:
                clean_head(str(root))
            self.assertEqual(caught.exception.reason, "state_unpinned")

            approvals = ApprovalAuthority()
            op = Operation(kind="ref", tool="t", arguments={}, repo=str(root), ref="main",
                           head=first)
            token = approvals.grant(approvals.request(op), granted_by="m", ttl_seconds=60)
            with self.assertRaises(ApprovalRejected) as caught:
                approvals.consume(token, op)
            self.assertEqual(caught.exception.reason, "state_unpinned")

            self.git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "two")
            token = approvals.grant(approvals.request(op), granted_by="m", ttl_seconds=60)
            with self.assertRaises(ApprovalRejected) as caught:
                approvals.consume(token, op)
            self.assertEqual(caught.exception.reason, "head_moved")


if __name__ == "__main__":
    unittest.main()
