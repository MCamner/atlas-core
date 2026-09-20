"""Hard deadline for the *CLI worker process*, not an in-process Python timeout.

The worker is trusted Atlas code with read-only tool registration. It runs as
our OS user, so this is NOT a filesystem/network sandbox or a permission grant.
On POSIX, a new session lets the parent kill the worker's entire process group
on timeout, cancellation or oversized output. Other platforms fail closed.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
import selectors
import signal
import subprocess
import time
from typing import Sequence


class WorkerDeadlineExceeded(TimeoutError):
    """The worker did not complete before the parent's monotonic deadline."""


class WorkerOutputExceeded(RuntimeError):
    """The worker exceeded its transport output cap."""


@dataclass(frozen=True)
class WorkerResult:
    stdout: bytes
    stderr: bytes
    returncode: int


def _kill_group(process: subprocess.Popen[bytes]) -> None:
    # A descendant can keep the pipes open after its parent exits. Kill the
    # whole session, not just the immediate process, and always reap the child.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    if process.poll() is None:
        process.kill()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def run_bounded_process(
    argv: Sequence[str], *, timeout: float, stdout_limit: int,
    stderr_limit: int = 16384,
) -> WorkerResult:
    """Execute trusted worker entrypoint with a parent-enforced hard deadline.

    Pipe reads are incremental and capped: a worker that prints forever cannot
    cause the parent to accumulate an unbounded `communicate()` buffer.
    Only POSIX process groups are supported; Windows needs a Job Object before
    this can be advertised as a descendant-safe boundary there.
    """
    if os.name != 'posix':
        raise RuntimeError('hard CLI process boundary requires POSIX')
    if not argv or timeout <= 0 or stdout_limit < 1 or stderr_limit < 1:
        raise ValueError('invalid process guard configuration')
    deadline = time.monotonic() + timeout
    process = subprocess.Popen(
        list(argv), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, start_new_session=True, close_fds=True,
    )
    assert process.stdout is not None and process.stderr is not None
    selector = selectors.DefaultSelector()
    chunks: dict[str, list[bytes]] = {'stdout': [], 'stderr': []}
    sizes = {'stdout': 0, 'stderr': 0}
    caps = {'stdout': stdout_limit, 'stderr': stderr_limit}
    try:
        selector.register(process.stdout, selectors.EVENT_READ, 'stdout')
        selector.register(process.stderr, selectors.EVENT_READ, 'stderr')
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise WorkerDeadlineExceeded('wall_seconds')
            ready = selector.select(remaining)
            if not ready:
                continue
            for key, _mask in ready:
                name: str = key.data
                block = os.read(key.fd, min(65536, caps[name] - sizes[name] + 1))
                if not block:
                    selector.unregister(key.fileobj)
                    continue
                sizes[name] += len(block)
                if sizes[name] > caps[name]:
                    raise WorkerOutputExceeded(name)
                chunks[name].append(block)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise WorkerDeadlineExceeded('wall_seconds')
        try:
            returncode = process.wait(timeout=remaining)
        except subprocess.TimeoutExpired as exc:
            raise WorkerDeadlineExceeded('wall_seconds') from exc
        return WorkerResult(
            stdout=b''.join(chunks['stdout']),
            stderr=b''.join(chunks['stderr']), returncode=returncode,
        )
    except BaseException:
        _kill_group(process)
        raise
    finally:
        selector.close()
        process.stdout.close()
        process.stderr.close()
