"""First write use case: a proposed patch becomes a new branch, once approved.

`prepare` never touches the user's repository. It checks that the repository
is at a clean commit, clones it (`--shared`, so no objects are copied), applies
the patch there, commits it, runs the host's test command in that clone and
computes the diff. Nothing so far has changed the repository.

The write is one tool, `create_branch`, run through `ToolGateway.invoke_write`
on a person's approval of the exact operation: branch name, commit, base and
diff digest. Its handler fetches that one commit into the repository and
creates `refs/heads/atlas/<name>` with `git update-ref <ref> <commit> <zero>`,
which git refuses if the ref already exists — a compare-and-swap, not a check
followed by a write. It does not move HEAD, touch the worktree, push, or merge.

Paths: a patch that names an absolute path, a `..` component, anything under
`.git`, a symlink or a submodule is refused before it is applied. Commands are
argument lists, never a shell string, so no text from the patch or the task is
ever parsed by a shell.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tempfile
import time
from typing import Any, Callable, Sequence

from .approval import ApprovalAuthority, Operation, clean_head
from .budget import RunBudget, RunLimits
from .eventlog import EventLog
from .redaction import redact_text
from .tool_gateway import ToolContext, ToolDefinition, ToolGateway

#: A new branch lives under `atlas/`, so a proposal can never name `main`,
#: a release branch, or anything a person already works on.
BRANCH = re.compile(r"atlas/[a-z0-9][a-z0-9._-]{0,62}")
_OID = re.compile(r"[0-9a-f]{40}([0-9a-f]{24})?")
#: Largest patch Core will apply and show. A person approves what they read.
MAX_PATCH_BYTES = 256 * 1024
#: How much of the test output is kept and shown.
MAX_TEST_OUTPUT = 8 * 1024
_REFUSED_MODES = re.compile(
    rb"^(?:new file mode|deleted file mode|old mode|new mode) (?:120000|160000)$", re.M
)


class ProposalRefused(ValueError):
    """The patch, branch or repository cannot be proposed as given."""


@dataclass(frozen=True)
class TestRun:
    argv: tuple[str, ...]
    exit_code: int | None
    seconds: float
    output: str
    timed_out: bool

    @property
    def passed(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


@dataclass(frozen=True)
class Proposal:
    repo: str
    base: str
    #: The local branch HEAD was on, at `base`, when the proposal was made.
    base_ref: str
    branch: str
    commit: str
    diff: str
    diff_sha256: str
    tests: TestRun
    #: The throwaway clone the commit lives in until it is fetched.
    workdir: str

    def operation(self) -> Operation:
        return Operation(
            kind="ref", tool="create_branch", arguments=self.arguments(),
            repo=self.repo, ref=f"refs/heads/{self.branch}", head=self.base,
        )

    def arguments(self) -> dict[str, Any]:
        return {
            "repo": self.repo, "branch": self.branch, "commit": self.commit,
            "base": self.base, "base_ref": self.base_ref,
            "diff_sha256": self.diff_sha256, "source": self.workdir,
        }


def _git(cwd: str | Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, timeout=60,
    )
    if check and result.returncode != 0:
        raise ProposalRefused(
            f"git {args[0]} failed: {result.stderr.decode('utf-8', 'replace').strip()[:300]}"
        )
    return result


def _diff(cwd: str | Path, base: str, commit: str) -> str:
    # Fixed flags, so a user's diff settings cannot change the approved bytes.
    return _git(
        cwd, "diff", "--binary", "--no-color", "--no-ext-diff", "--no-renames",
        base, commit,
    ).stdout.decode("utf-8", "replace")


def validate_branch(name: str) -> str:
    if (not BRANCH.fullmatch(name) or ".." in name or name.endswith((".lock", "."))):
        raise ProposalRefused(f"branch must match {BRANCH.pattern}: {name!r}")
    return name


def _safe_path(path: str) -> None:
    pure = PurePosixPath(path)
    if not path or pure.is_absolute() or "\\" in path:
        raise ProposalRefused(f"patch path is not relative: {path!r}")
    if any(part in ("..", "") for part in path.split("/")):
        raise ProposalRefused(f"patch path leaves the repository: {path!r}")
    if any(part.lower() == ".git" for part in pure.parts):
        raise ProposalRefused(f"patch path is inside .git: {path!r}")


def patch_paths(workdir: str | Path, patch_file: Path) -> list[str]:
    """Every path the patch touches, refused if any is unsafe."""
    raw = patch_file.read_bytes()
    if _REFUSED_MODES.search(raw):
        raise ProposalRefused("patch creates or changes a symlink or submodule")
    listed = _git(workdir, "apply", "--numstat", "-z", str(patch_file)).stdout
    # Records: "added\tdeleted\tpath\0", or for a rename
    # "added\tdeleted\t\0old\0new\0".
    paths: list[str] = []
    fields = listed.split(b"\0")
    index = 0
    while index < len(fields) and fields[index]:
        head = fields[index].split(b"\t", 2)
        if len(head) != 3:
            raise ProposalRefused("cannot read the paths the patch touches")
        if head[2]:
            paths.append(head[2].decode("utf-8"))
            index += 1
        else:
            paths.extend(p.decode("utf-8") for p in fields[index + 1:index + 3])
            index += 3
    if not paths:
        raise ProposalRefused("patch changes nothing")
    for path in paths:
        _safe_path(path)
    return paths


def _run_tests(argv: Sequence[str], cwd: str, timeout: float) -> TestRun:
    started = time.monotonic()
    try:
        result = subprocess.run(
            list(argv), cwd=cwd, capture_output=True, timeout=timeout, shell=False,
        )
        code: int | None = result.returncode
        raw = result.stdout + result.stderr
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        code, timed_out = None, True
        raw = (exc.stdout or b"") + (exc.stderr or b"")
    except OSError as exc:
        code, timed_out, raw = 127, False, str(exc).encode("utf-8")
    output = redact_text(raw.decode("utf-8", "replace")[-MAX_TEST_OUTPUT:])
    return TestRun(tuple(argv), code, round(time.monotonic() - started, 3), output, timed_out)


def prepare(
    repo: str, patch: bytes, branch: str, test_argv: Sequence[str], *,
    test_timeout: float = 300.0,
) -> Proposal:
    """Build and test the proposal in a clone. Changes nothing in `repo`."""
    validate_branch(branch)
    if not test_argv:
        raise ProposalRefused("a proposal runs the repository's tests; give a test command")
    if not patch.strip():
        raise ProposalRefused("patch is empty")
    if len(patch) > MAX_PATCH_BYTES:
        raise ProposalRefused(f"patch is larger than {MAX_PATCH_BYTES} bytes")
    root = str(Path(repo).expanduser().resolve())
    base = clean_head(root)
    # The branch the base commit is on is part of what was approved: the write
    # verifies it in the same transaction that creates the new branch.
    base_ref = _git(root, "symbolic-ref", "-q", "HEAD", check=False).stdout.decode().strip()
    if not base_ref.startswith("refs/heads/"):
        raise ProposalRefused("HEAD is detached; a proposal needs a local branch as its base")
    if _git(root, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}",
            check=False).returncode == 0:
        raise ProposalRefused(f"branch {branch} already exists")
    workdir = tempfile.mkdtemp(prefix="atlas-proposal-")
    try:
        clone = str(Path(workdir) / "clone")
        _git(workdir, "clone", "-q", "--shared", "--no-checkout", root, clone)
        _git(clone, "checkout", "-q", "--detach", base)
        patch_file = Path(workdir) / "change.patch"
        patch_file.write_bytes(patch)
        patch_paths(clone, patch_file)
        _git(clone, "apply", "--index", str(patch_file))
        _git(clone, "-c", "user.name=Atlas Core", "-c", "user.email=atlas-core@localhost",
             "commit", "-q", "--no-verify", "-m", f"atlas: proposed change on {branch}")
        commit = _git(clone, "rev-parse", "HEAD").stdout.decode().strip()
        diff = _diff(clone, base, commit)
        tests = _run_tests(test_argv, clone, test_timeout)
    except BaseException:
        shutil.rmtree(workdir, ignore_errors=True)
        raise
    return Proposal(
        repo=root, base=base, base_ref=base_ref, branch=branch, commit=commit, diff=diff,
        diff_sha256=hashlib.sha256(diff.encode("utf-8")).hexdigest(),
        tests=tests, workdir=clone,
    )


def _create_branch(_ctx: ToolContext, args: dict[str, Any]) -> dict[str, str]:
    """The write. Fetches one commit and creates the ref only if it is absent."""
    repo, commit, ref = args["repo"], args["commit"], f"refs/heads/{args['branch']}"
    _git(repo, "fetch", "-q", "--no-tags", "--no-write-fetch-head", args["source"], commit)
    parent = _git(repo, "rev-parse", f"{commit}^").stdout.decode().strip()
    if parent != args["base"]:
        raise ProposalRefused("fetched commit is not a child of the approved base")
    shown = hashlib.sha256(_diff(repo, args["base"], commit).encode("utf-8")).hexdigest()
    if shown != args["diff_sha256"]:
        raise ProposalRefused("fetched commit is not the diff that was approved")
    # One transaction: git applies both or neither. The approval was for a
    # branch cut from `base` while `base_ref` stood there; if it moved after
    # the approval was checked, the new branch is not created. (HEAD itself is
    # checked by the approval; git refuses a second update of the same ref
    # through the HEAD symref in one transaction.)
    _check_ref(args["base_ref"])
    transaction = (
        f"verify {args['base_ref']} {args['base']}\n"
        f"create {ref} {commit}\n"
    )
    created = subprocess.run(
        ["git", "-C", repo, "update-ref", "-m", "atlas: approved proposal", "--stdin"],
        input=transaction.encode("utf-8"), capture_output=True, timeout=60,
    )
    if created.returncode != 0:
        raise ProposalRefused(
            "the repository moved or the branch appeared before the write: "
            + created.stderr.decode("utf-8", "replace").strip()[:300]
        )
    return {"ref": ref, "commit": commit}


def _check_ref(name: str) -> str:
    # These go into an `update-ref --stdin` transaction: a newline or a space
    # in one would be a second instruction.
    if (not name.startswith("refs/heads/") or any(c.isspace() for c in name)
            or subprocess.run(["git", "check-ref-format", name],
                              capture_output=True).returncode != 0):
        raise ProposalRefused(f"not a branch ref: {name!r}")
    return name


def describe_create_branch(args: dict[str, Any]) -> Operation:
    """What `create_branch` with these arguments does, for the approval."""
    _check_ref(args["base_ref"])
    if not _OID.fullmatch(args["commit"]):
        raise ProposalRefused("commit must be a full object id")
    return Operation(
        kind="ref", tool="create_branch", arguments=args, repo=args["repo"],
        ref=f"refs/heads/{validate_branch(args['branch'])}", head=args["base"],
    )


CREATE_BRANCH = ToolDefinition(
    "create_branch", "write", _create_branch, describe=describe_create_branch,
    timeout_seconds=60.0,
    input_schema={
        "type": "object", "additionalProperties": False,
        "required": ["repo", "branch", "commit", "base", "base_ref", "diff_sha256", "source"],
        "properties": {name: {"type": "string"} for name in
                       ("repo", "branch", "commit", "base", "base_ref", "diff_sha256",
                        "source")},
    },
    output_schema={"type": "object", "required": ["ref", "commit"]},
)


def discard(proposal: Proposal) -> None:
    shutil.rmtree(Path(proposal.workdir).parent, ignore_errors=True)


#: What `propose` can end in, and the exit code each gives.
OUTCOMES: dict[str, int] = {
    "branch_created": 0,
    "tests_failed": 2,
    "approval_required": 3,
    "refused": 3,
}
#: How long a person's yes lasts. They are at the terminal; this is the time
#: between typing it and the write, not a standing permission.
GRANT_TTL_SECONDS = 300


def render(proposal: Proposal) -> str:
    """What the person reads before answering: the whole diff and the tests."""
    op = proposal.operation()
    tests = proposal.tests
    verdict = "timed out" if tests.timed_out else f"exit {tests.exit_code}"
    return "\n".join([
        f"repository : {proposal.repo}",
        f"base       : {proposal.base}",
        f"new branch : {proposal.branch} -> {proposal.commit}",
        f"tests      : {' '.join(tests.argv)} ({verdict}, {tests.seconds}s)",
        tests.output.rstrip(),
        "",
        proposal.diff.rstrip(),
        "",
        f"operation  : {op.sha256}",
    ])


def propose(
    repo: str, patch: bytes, branch: str, test_argv: Sequence[str], *,
    ask: Callable[[str], str] | None,
    granted_by: str,
    log: EventLog | None = None,
    test_timeout: float = 300.0,
) -> dict[str, Any]:
    """Prepare, test, show, ask, and write only on an exact yes.

    `ask` shows the rendered proposal to a person and returns what they typed;
    `None` means nobody can be asked, which ends in `approval_required` with
    nothing written. The answer that approves is the first 12 characters of the
    operation digest, so a yes names what it is a yes to.
    """
    proposal = prepare(repo, patch, branch, test_argv, test_timeout=test_timeout)
    try:
        op = proposal.operation()
        summary: dict[str, Any] = {
            "repo": proposal.repo, "base": proposal.base, "branch": proposal.branch,
            "commit": proposal.commit, "diff_sha256": proposal.diff_sha256,
            "operation_sha256": op.sha256,
            "tests": {"argv": list(proposal.tests.argv), "exit_code": proposal.tests.exit_code,
                      "timed_out": proposal.tests.timed_out, "seconds": proposal.tests.seconds},
            "approval_id": None,
        }
        if not proposal.tests.passed:
            return {**summary, "outcome": "tests_failed"}
        approvals = ApprovalAuthority(log=log)
        approval_id = approvals.request(op)
        summary["approval_id"] = approval_id
        if ask is None:
            return {**summary, "outcome": "approval_required"}
        answer = ask(render(proposal))
        if answer.strip() != op.sha256[:12]:
            approvals.refuse(approval_id, refused_by=granted_by)
            return {**summary, "outcome": "refused"}
        token = approvals.grant(approval_id, granted_by=granted_by,
                                ttl_seconds=GRANT_TTL_SECONDS)
        gateway = ToolGateway(
            budget=RunBudget(RunLimits(wall_seconds=120, model_calls=0, tool_calls=1,
                                       tokens=0, output_bytes=4096)),
            tools={"create_branch": CREATE_BRANCH}, log=log, approvals=approvals,
        )
        gateway.invoke_write("create_branch", proposal.arguments(), token=token)
        return {**summary, "outcome": "branch_created"}
    finally:
        discard(proposal)


__all__ = [
    "BRANCH",
    "CREATE_BRANCH",
    "GRANT_TTL_SECONDS",
    "MAX_PATCH_BYTES",
    "OUTCOMES",
    "Proposal",
    "ProposalRefused",
    "TestRun",
    "describe_create_branch",
    "discard",
    "patch_paths",
    "prepare",
    "propose",
    "render",
    "validate_branch",
]
