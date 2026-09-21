"""Optional hard process boundary for trusted, serializable Python adapters.

`AtlasController.run` stays cooperative. Hosts requiring a hard deadline must
use `run_isolated` or an equivalent external worker boundary. This is NOT an
OS filesystem/network sandbox: code retains the caller's privileges.
"""
from __future__ import annotations

import json
import multiprocessing
from multiprocessing.connection import Connection
import os
import signal
import time
from typing import Any, Callable, TYPE_CHECKING

from .budget import RunLimits
from .machine import STOP_REASONS
from .state import AtlasRunState

if TYPE_CHECKING:
    from .budget import RunBudget
    from .controller import AtlasController
    from .evidence_base import EvidenceBase
    from .observer import Observer


def _run_worker(
    channel: Connection, controller: AtlasController, task: str,
    observations: list[str] | None, evidence: EvidenceBase | None,
    readers: list[Callable[[str, RunBudget], list[str]]] | None,
    limits: RunLimits, observer: Observer | None = None,
) -> None:
    # Start an independent POSIX session before any model or source reads.
    os.setsid()
    try:
        run = controller.run(
            task, observations=observations, evidence=evidence, readers=readers,
            observer=observer, json_mode=True, limits=limits,
        )
        run.setdefault('metadata', {})['isolation'] = 'spawned_process'
        payload: dict[str, Any] = {'kind': 'run', 'run': run}
    except BaseException as exc:
        payload = {'kind': 'error', 'error': type(exc).__name__}
    try:
        channel.send_bytes(json.dumps(payload, ensure_ascii=False).encode('utf-8'))
    except (OSError, ValueError, TypeError):
        # Parent reports a runtime failure, never an inferred PASS.
        pass
    finally:
        channel.close()


def _kill_worker(process: Any) -> None:
    # Multiprocessing's spawn factory returns SpawnProcess, not the abstract
    # multiprocessing.Process constructor. Both implement this runtime API.
    if process.pid is not None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        if process.is_alive():
            process.kill()
    process.join(timeout=2)
    if process.is_alive():
        process.kill()
        process.join()


def _failure(
    controller: AtlasController, task: str, reason: str, detail: str,
) -> dict[str, Any]:
    state = AtlasRunState(task=task, max_iterations=controller.max_iterations)
    state.enter('observing')
    if reason == 'budget_exhausted':
        state.metadata['budget_exhausted'] = detail
    else:
        state.metadata['failure'] = {
            'stage': 'isolated_controller', 'error': detail[:128],
            'message': 'Isolated worker did not return a verified run document.',
        }
    state.metadata['isolation'] = 'spawned_process'
    if reason == 'cancelled':
        state.stop('cancelled')
    elif reason == 'budget_exhausted':
        state.stop('budget_exhausted')
    else:
        state.stop('tool_error')
    return state.to_dict()


def run_isolated(
    controller: AtlasController, task: str, *, limits: RunLimits,
    observations: list[str] | None = None,
    evidence: EvidenceBase | None = None,
    readers: list[Callable[[str, RunBudget], list[str]]] | None = None,
    observer: Observer | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Run a controller with a parent-enforced hard POSIX deadline.

    Controller, model, observer and reader/handler callbacks must be picklable
    by the `spawn` start method. All tool calls and retries share one worker RunBudget.
    The parent bounds the whole run including startup and IPC, and can cancel
    a stuck callback by terminating its process group. It cannot undo side
    effects committed before termination. This is not a privilege sandbox.
    """
    if os.name != 'posix':
        return _failure(controller, task, 'tool_error', 'POSIX_process_isolation_required')
    if not isinstance(limits, RunLimits):
        raise TypeError('run_isolated requires explicit RunLimits')
    ctx = multiprocessing.get_context('spawn')
    receive, send = ctx.Pipe(duplex=False)
    process = ctx.Process(
        target=_run_worker,
        args=(send, controller, task, observations, evidence, readers, limits, observer),
        daemon=False,
    )
    deadline = time.monotonic() + limits.wall_seconds
    cap = min(16 * 1024 * 1024, max(262144, limits.output_bytes * 8 + 65536))
    try:
        try:
            process.start()
        except Exception as exc:
            # Includes pickle.PicklingError for untrusted/non-importable
            # callbacks; never escape the intended fail-closed run contract.
            return _failure(controller, task, 'tool_error', type(exc).__name__)
        finally:
            send.close()
        while True:
            if cancelled is not None and cancelled():
                return _failure(controller, task, 'cancelled', 'external_cancel')
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return _failure(controller, task, 'budget_exhausted', 'wall_seconds')
            if receive.poll(min(remaining, 0.05)):
                try:
                    raw = receive.recv_bytes(maxlength=cap)
                    payload = json.loads(raw.decode('utf-8'))
                except (EOFError, OSError, UnicodeError, ValueError) as exc:
                    return _failure(controller, task, 'tool_error', type(exc).__name__)
                if not isinstance(payload, dict) or payload.get('kind') != 'run':
                    return _failure(controller, task, 'tool_error',
                                    str(payload.get('error', 'WorkerProtocolError'))[:128]
                                    if isinstance(payload, dict) else 'WorkerProtocolError')
                run = payload.get('run')
                if not isinstance(run, dict) or run.get('schema') != 'atlas-run.v1':
                    return _failure(controller, task, 'tool_error', 'WorkerProtocolError')
                reason = run.get('stop_reason')
                if reason not in STOP_REASONS or run.get('status') != STOP_REASONS[reason].status:
                    return _failure(controller, task, 'tool_error', 'WorkerProtocolError')
                return run
            if process.exitcode is not None:
                return _failure(controller, task, 'tool_error', 'WorkerExitedWithoutResult')
    finally:
        if process.pid is not None:
            _kill_worker(process)
        receive.close()
        send.close()
