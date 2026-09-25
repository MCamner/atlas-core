"""Write approval: a person's yes to one exact operation, spent once.

Atlas Core has been read-only because nothing could state *what* was approved.
This module is the smallest thing that can, and it grants nothing on its own:

- An `Operation` is the exact write — tool, arguments, repository, ref and the
  clean commit it was proposed against — and its digest is what gets approved.
- `ApprovalAuthority` is held by host code. It records a request, and a grant or
  refusal that only the host can supply (the answer comes from a person through
  the host's own UI or CLI). A grant returns a token once; the authority keeps
  only the token's digest.
- `consume` spends a token for one operation: unknown, refused, expired, already
  spent, a different operation, or a repository whose state moved since the
  request are each a refusal with a reason, and a refusal is recorded.

Model text never reaches this module: the gateway's `invoke_write` is the only
caller, and host code — not a model adapter — calls that. Approval-like prose in
a task, a README or model output stays data.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import re
import secrets
import threading
import time
from typing import Any, Callable, Mapping, NoReturn

from .eventlog import APPROVAL_DECISIONS, EventLog, digest
from .snapshot import UNKNOWN, take_snapshot

#: What a write can be. The same vocabulary as `atlas-approval.v1.binds_to.kind`.
OPERATION_KINDS: tuple[str, ...] = ("diff", "command", "ref")

#: Longest a grant may live. A person approves what they saw now; an approval
#: that outlives the afternoon approves a state nobody looked at.
MAX_TTL_SECONDS = 3600

_COMMIT = re.compile(r"[0-9a-f]{40}([0-9a-f]{24})?")


class ApprovalRejected(PermissionError):
    """A write was refused because no valid approval covers it."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Operation:
    """One exact write. Its digest is the thing a person approves."""

    kind: str
    tool: str
    arguments: Mapping[str, Any]
    repo: str
    ref: str
    #: The clean commit the operation was proposed against. A dirty or unknown
    #: worktree has no commit that pins its bytes, so it cannot be approved.
    head: str

    def __post_init__(self) -> None:
        if self.kind not in OPERATION_KINDS:
            raise ValueError(f"kind must be one of {OPERATION_KINDS}")
        if not self.tool or not self.repo or not self.ref:
            raise ValueError("an operation names its tool, repository and ref")
        if not _COMMIT.fullmatch(self.head):
            raise ValueError("head must be a full commit id")

    @property
    def sha256(self) -> str:
        return digest({
            "kind": self.kind, "tool": self.tool, "arguments": dict(self.arguments),
            "repo": self.repo, "ref": self.ref, "head": self.head,
        })


def clean_head(root: str) -> str:
    """The commit at `root`, or `ApprovalRejected` if it does not pin the bytes.

    The default state probe. An uncommitted change leaves HEAD where it was, so
    a commit alone would let an approval survive an edit it never saw.
    """
    snapshot = take_snapshot(root)
    if snapshot.commit == UNKNOWN or snapshot.worktree_state != "clean":
        raise ApprovalRejected("state_unpinned")
    return snapshot.commit


@dataclass
class _Pending:
    operation: Operation
    iteration: int
    token_sha256: str | None = None
    granted_by: str | None = None
    granted_at: float | None = None
    expires_at: float | None = None
    decision: str = "requested"


class ApprovalAuthority:
    """Host-held. Issues, refuses and spends approvals; records each step."""

    def __init__(
        self,
        *,
        log: EventLog | None = None,
        head_of: Callable[[str], str] = clean_head,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._log = log
        self._head_of = head_of
        self._clock = clock
        self._pending: dict[str, _Pending] = {}
        # Check-then-spend is one step, or two threads spend one token.
        self._lock = threading.Lock()

    def _record(self, decision: str, approval_id: str, item: _Pending, **extra: Any) -> None:
        if self._log is None:
            return
        self._log.append(
            "approval_recorded",
            iteration=item.iteration,
            decision=decision,
            approval_id=approval_id,
            operation_sha256=item.operation.sha256,
            operation_kind=item.operation.kind,
            tool=item.operation.tool,
            repo=item.operation.repo,
            ref=item.operation.ref,
            head=item.operation.head,
            **extra,
        )

    def request(self, operation: Operation, *, iteration: int = 0) -> str:
        """Record that `operation` needs a person, and return its approval id."""
        approval_id = f"approval-{operation.sha256[:16]}-{len(self._pending)}"
        item = _Pending(operation=operation, iteration=iteration)
        self._pending[approval_id] = item
        self._record("requested", approval_id, item)
        return approval_id

    def _open(self, approval_id: str) -> _Pending:
        item = self._pending.get(approval_id)
        if item is None:
            raise KeyError(f"no approval request {approval_id!r}")
        if item.decision != "requested":
            raise ValueError(f"{approval_id!r} was already answered: {item.decision}")
        return item

    def grant(self, approval_id: str, *, granted_by: str, ttl_seconds: float) -> str:
        """A person's yes. Returns the token once; only its digest is kept."""
        if not granted_by.strip():
            raise ValueError("a grant names who gave it")
        if not 0 < ttl_seconds <= MAX_TTL_SECONDS:
            raise ValueError(f"ttl_seconds must be in (0, {MAX_TTL_SECONDS}]")
        item = self._open(approval_id)
        token = secrets.token_urlsafe(32)
        item.token_sha256 = hashlib.sha256(token.encode("ascii")).hexdigest()
        item.granted_by = granted_by
        item.granted_at = self._clock()
        item.expires_at = item.granted_at + ttl_seconds
        item.decision = "granted"
        self._record(
            "granted", approval_id, item, granted_by=granted_by,
            expires_at=_iso(item.expires_at),
        )
        return token

    def refuse(self, approval_id: str, *, refused_by: str) -> None:
        item = self._open(approval_id)
        item.decision = "refused"
        item.granted_by = refused_by
        item.granted_at = self._clock()
        self._record("refused", approval_id, item, granted_by=refused_by)

    def consume(self, token: str, operation: Operation, *, iteration: int = 0) -> str:
        """Spend `token` on `operation`, or raise `ApprovalRejected`.

        Checked in order: is this an approval at all, is it still valid, is the
        repository still in the state the person looked at, and is it for
        *this* operation. Returns the approval id.
        """
        with self._lock:
            return self._consume(token, operation, iteration)

    def _consume(self, token: str, operation: Operation, iteration: int) -> str:
        token_sha256 = hashlib.sha256(token.encode("utf-8")).hexdigest()
        found = [
            (approval_id, item) for approval_id, item in self._pending.items()
            if item.token_sha256 is not None
            and secrets.compare_digest(item.token_sha256, token_sha256)
        ]
        if not found:
            self._reject_unknown(operation, iteration)
        approval_id, item = found[0]
        if item.decision == "consumed":
            self._reject(approval_id, item, "already_used")
        if item.decision != "granted" or item.expires_at is None:
            self._reject(approval_id, item, "not_granted")
        if self._clock() >= item.expires_at:
            self._reject(approval_id, item, "expired")
        # State before digest: a tool describes its operation against the HEAD
        # it sees now, so after a move the digests differ too, and the reason
        # a person needs to read is that the repository moved.
        try:
            current = self._head_of(item.operation.repo)
        except ApprovalRejected as exc:
            self._reject(approval_id, item, exc.reason)
        if current != item.operation.head:
            self._reject(approval_id, item, "head_moved", current_head=current)
        if operation.sha256 != item.operation.sha256:
            self._reject(approval_id, item, "operation_mismatch",
                         offered_sha256=operation.sha256)
        item.decision = "consumed"
        self._record("consumed", approval_id, item, granted_by=item.granted_by)
        return approval_id

    def _reject(self, approval_id: str, item: _Pending, reason: str, **extra: Any) -> NoReturn:
        self._record("rejected", approval_id, item, reason=reason, **extra)
        raise ApprovalRejected(reason)

    def _reject_unknown(self, operation: Operation, iteration: int) -> NoReturn:
        self._record(
            "rejected", "unknown", _Pending(operation=operation, iteration=iteration),
            reason="unknown_token",
        )
        raise ApprovalRejected("unknown_token")

    def record(self, approval_id: str, *, run_id: str) -> dict[str, Any]:
        """The `atlas-approval.v1` document for one request."""
        item = self._pending[approval_id]
        granted = {"requested": None, "refused": False}.get(item.decision, True)
        return {
            "schema": "atlas-approval.v1",
            "approval_id": approval_id,
            "run_id": run_id,
            "iteration": item.iteration,
            "required": True,
            "reason": f"{item.operation.kind} write via {item.operation.tool}",
            "granted": granted,
            "granted_by": item.granted_by,
            "granted_at": _iso(item.granted_at) if item.granted_at is not None else None,
            "binds_to": {
                "kind": item.operation.kind,
                "sha256": item.operation.sha256,
                "repo": item.operation.repo,
                "ref": item.operation.ref,
            } if granted else None,
        }


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat()


__all__ = [
    "APPROVAL_DECISIONS",
    "MAX_TTL_SECONDS",
    "OPERATION_KINDS",
    "ApprovalAuthority",
    "ApprovalRejected",
    "Operation",
    "clean_head",
]
