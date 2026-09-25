from __future__ import annotations
import argparse, json, sys
from pathlib import Path
from typing import Any, Callable, Literal
from .budget import RunBudget, RunLimits
from . import __version__
from .controller import AtlasController
from .router import list_routes
from .adapters.filesystem_repo import FilesystemRepoAdapter, FilesystemRepoObserver
from .adapters.github_reader import GitHubRepoAdapter
from .adapters.mqobsidian import MQObsidianMemoryAdapter
from .skill_generator import generate_chatgpt_skill
from .finalizer import render_run_text
from .eventlog import JsonlSink, ResumeRefused
from .evidence_base import EvidenceBase
from .snapshot import take_snapshot
from .inspect_run import InspectError, inspect_run, render_inspection
from .host_api import (
    EventLogInUse, FollowEnded, RunIdInUse, log_holds_a_run, seal_lost_run, cancel_requested, dump_jsonl, follow_events,
    new_run_id, request_cancel, run_status, validate_run_id,
)
from .machine import STOP_REASONS, exit_codes
from .process_guard import (
    WorkerDeadlineExceeded, WorkerOutputExceeded, run_bounded_process,
)
from .state import AtlasRunState

# Exit codes are derived from the same table the controller enforces.
EXIT_CODES: dict[str, int] = exit_codes()
UNKNOWN_STOP_REASON_EXIT = 1


def _print_run(run: dict, *, json_mode: bool) -> int:
    if json_mode:
        print(json.dumps(run, ensure_ascii=False, indent=2))
    else:
        print(render_run_text(run))
    return EXIT_CODES.get(run.get('stop_reason') or '', UNKNOWN_STOP_REASON_EXIT)


class WorkerResultUnavailable(Exception):
    """The worker logged its own stop, but its run document never arrived."""

    def __init__(self, error: dict[str, Any]) -> None:
        super().__init__(error['message'])
        self.error = error


def _worker_failure(
    args: argparse.Namespace, *,
    reason: Literal['budget_exhausted', 'tool_error', 'cancelled'],
    detail: str, error: str,
) -> dict:
    # The worker may be stuck or have been killed. Never synthesize a graded
    # answer, old evaluations, or a successful run from its partial stdout.
    state = AtlasRunState(task=args.task, max_iterations=args.max_iterations)
    if args.run_id:
        state.run_id = args.run_id
    state.enter('observing')
    if args.event_log:
        # The log is the audit source: seal the lost run there. A stop the
        # worker already logged means the run ended and only its result was
        # lost; the parent holds that terminal event, not the run document.
        try:
            logged, sealed = seal_lost_run(
                args.event_log, args.run_id, stop_reason=reason, detail=detail[:512],
                task=args.task, max_iterations=args.max_iterations,
            )
        except (ResumeRefused, EventLogInUse, InspectError, OSError, ValueError) as exc:
            state.metadata['event_log_unsealed'] = str(exc)[:512]
        else:
            if not sealed:
                raise WorkerResultUnavailable({
                    'error': 'worker_result_unavailable',
                    'run_id': args.run_id,
                    'event_log': args.event_log,
                    'logged_stop_reason': logged,
                    'transport_error': error,
                    'message': detail[:512],
                })
    if reason == 'budget_exhausted':
        state.metadata['budget_exhausted'] = detail
    else:
        state.metadata['failure'] = {
            'stage': 'cli_worker', 'error': error, 'message': detail[:512],
        }
    state.stop(reason)
    return state.to_dict()


def _run_worker(args: argparse.Namespace) -> int:
    # Only the *public* CLI entrypoint (`main()` with argv=None) takes this
    # outer boundary. Embedded `main([...])` and `AtlasController.run()` are
    # in-process APIs and retain their documented cooperative contract.
    limits = RunLimits(
        wall_seconds=args.wall_seconds, model_calls=0,
        tool_calls=args.max_tool_calls, tokens=0,
        output_bytes=args.max_output_bytes,
    )
    extra: list[str] = []
    if args.event_log:
        if log_holds_a_run(args.event_log):
            # Checked again, under the writer lock, in the worker. Refusing
            # here keeps a refused start from being reported as a failed run.
            print(f"atlas run: {args.event_log} already holds a run; "
                  "one run per event log", file=sys.stderr)
            return 1
        if not args.run_id:
            # The parent must know the id to seal the run if it loses the worker.
            args.run_id = new_run_id()
            extra = ['--run-id', args.run_id]
    command = [sys.executable, '-m', 'atlas_core.worker_cli', *sys.argv[1:], *extra, '--json']
    # JSON repeats some source text in several fields. Limit the transport
    # independently of the controller's tighter observation/output quota.
    stdout_cap = min(16 * 1024 * 1024, max(262144, limits.output_bytes * 8 + 65536))
    try:
        result = run_bounded_process(
            command, timeout=limits.wall_seconds,
            stdout_limit=stdout_cap, stderr_limit=65536,
        )
    except WorkerDeadlineExceeded:
        run = _worker_failure(
            args, reason='budget_exhausted', detail='wall_seconds', error='WorkerDeadlineExceeded',
        )
    except WorkerOutputExceeded as exc:
        run = _worker_failure(
            args, reason='budget_exhausted', detail=f'worker_{exc}_bytes',
            error='WorkerOutputExceeded',
        )
    except KeyboardInterrupt:
        run = _worker_failure(
            args, reason='cancelled', detail='user_interrupt', error='KeyboardInterrupt',
        )
    except (OSError, RuntimeError) as exc:
        run = _worker_failure(
            args, reason='tool_error', detail=str(exc), error=type(exc).__name__,
        )
    else:
        try:
            run = json.loads(result.stdout.decode('utf-8'))
            if not isinstance(run, dict) or run.get('schema') != 'atlas-run.v1':
                raise ValueError('worker did not return an atlas-run.v1 object')
            reason = run.get('stop_reason')
            if (reason not in STOP_REASONS
                    or run.get('status') != STOP_REASONS[reason].status
                    or result.returncode != EXIT_CODES[reason]):
                raise ValueError('worker status and exit code disagree')
        except (UnicodeError, json.JSONDecodeError, ValueError, TypeError) as exc:
            run = _worker_failure(
                args, reason='tool_error', detail=str(exc), error='WorkerProtocolError',
            )
    return _print_run(run, json_mode=args.json)


def _run_hard_cli(args: argparse.Namespace) -> int:
    try:
        return _run_worker(args)
    except WorkerResultUnavailable as lost:
        # No run document on stdout: the host reads the run from the log.
        if args.json:
            print(json.dumps(lost.error, ensure_ascii=False), file=sys.stderr)
        else:
            print(f"atlas run: worker result unavailable ({lost.error['transport_error']}); "
                  f"run {args.run_id!r} stopped {lost.error['logged_stop_reason']} in "
                  f"{args.event_log} — see `atlas inspect`", file=sys.stderr)
        return 1


def _start(start: Callable[[], dict]) -> dict | None:
    try:
        return start()
    except (RunIdInUse, EventLogInUse) as exc:
        print(f"atlas run: {exc}", file=sys.stderr)
        return None


def _host_command(args: argparse.Namespace) -> int:
    """status / cancel / events: exit 0 answered, 1 cannot answer, 2 the answer
    is that the request cannot be met (finished, interrupted, timed out)."""
    name = f"atlas {args.command}"
    try:
        validate_run_id(args.run_id)
        if args.command == 'events':
            if not args.follow:
                status = run_status(args.event_log, args.run_id)
                if status['state'] == 'not_found':
                    print(f"{name}: run {args.run_id!r} not found", file=sys.stderr)
                    return 1
            try:
                for record in follow_events(
                    args.event_log, args.run_id,
                    timeout=args.timeout if args.follow else 0.0,
                ):
                    print(dump_jsonl(record), flush=True)
            except FollowEnded as ended:
                if args.follow:
                    print(f"{name}: {ended.reason} before run_stopped", file=sys.stderr)
                    return 2
            return 0
        status = run_status(args.event_log, args.run_id)
        if args.command == 'cancel':
            if status['state'] in ('finished', 'interrupted'):
                print(f"{name}: run {args.run_id!r} already {status['state']}; "
                      "nothing to cancel", file=sys.stderr)
                return 2
            request_cancel(args.event_log, args.run_id)
            status['cancel_requested'] = True
    except (InspectError, ValueError) as exc:
        print(f"{name}: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(status, ensure_ascii=False, indent=2))
    else:
        print(f"{status['run_id']}: {status['state']}"
              + (f" ({status['stop_reason']})" if status['stop_reason'] else "")
              + (" — cancel requested" if status['cancel_requested'] else ""))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog='atlas', description='Atlas Core loop engine')
    sub = parser.add_subparsers(dest='command', required=True)
    run_p = sub.add_parser('run', help='Run Atlas loop for a task')
    run_p.add_argument('task', help='Task to run')
    run_p.add_argument('--max-iterations', type=int, default=2, help='Max loop iterations')
    run_p.add_argument('--wall-seconds', type=float, default=30.0, help='Wall-clock limit (default 30s)')
    run_p.add_argument('--max-tool-calls', type=int, default=32, help='Shared observation/tool call limit')
    run_p.add_argument('--max-output-bytes', type=int, default=65536, help='Combined observation/output UTF-8 limit')
    run_p.add_argument('--unsafe-legacy-unbounded', action='store_true', help='Explicitly opt into legacy unmetered mode and memory output')
    run_p.add_argument('--memory-dir', default=None, help='Optional local memory output directory')
    run_p.add_argument('--json', action='store_true', help='Print full run state as JSON')
    run_p.add_argument('--repo', default=None, help='Optional GitHub repo in owner/name form to observe before running')
    run_p.add_argument('--repo-ref', default=None, help='Optional branch/ref for --repo')
    run_p.add_argument('--repo-path', default=None, help='Local repo read as evidence (Observation.v1) inside the run')
    run_p.add_argument('--mqobsidian-path', default=None, help='Optional mqobsidian vault path')
    run_p.add_argument('--mq-project', default=None, help='Project name for mqobsidian context')
    run_p.add_argument('--event-log', default=None, help='Append run events to this JSONL file')
    run_p.add_argument('--run-id', default=None, help='Run ID from `atlas create`; requires --event-log')
    sub.add_parser('create', help='Allocate a run ID for a later `atlas run --run-id`')
    status_p = sub.add_parser('status', help='Report whether a run is running, finished or interrupted')
    status_p.add_argument('run_id', help='Run ID')
    status_p.add_argument('--event-log', required=True, help='JSONL event log the run writes')
    status_p.add_argument('--json', action='store_true', help='Print atlas-status.v1 JSON')
    cancel_p = sub.add_parser('cancel', help='Ask a run to stop at its next boundary')
    cancel_p.add_argument('run_id', help='Run ID')
    cancel_p.add_argument('--event-log', required=True, help='JSONL event log the run writes')
    cancel_p.add_argument('--json', action='store_true', help='Print atlas-status.v1 JSON')
    events_p = sub.add_parser('events', help='Print one run\'s atlas-event.v1 records as JSONL')
    events_p.add_argument('run_id', help='Run ID')
    events_p.add_argument('--event-log', required=True, help='JSONL event log the run writes')
    events_p.add_argument('--follow', action='store_true', help='Stream new events until run_stopped')
    events_p.add_argument('--timeout', type=float, default=60.0, help='Give up following after this many seconds')
    inspect_p = sub.add_parser('inspect', help='Inspect one run from an event log')
    inspect_p.add_argument('run_id', help='Run ID to inspect')
    inspect_p.add_argument('--event-log', required=True, help='JSONL event log to read')
    inspect_p.add_argument('--json', action='store_true', help='Export the inspection as JSON')
    skill_p = sub.add_parser('generate-skill', help='Generate a ChatGPT Skill package')
    skill_p.add_argument('output_dir', help='Parent directory for the generated skill')
    skill_p.add_argument('--force', action='store_true', help='Overwrite generated skill files')
    sub.add_parser('routes', help='List available routes')
    sub.add_parser('version', help='Show version')
    args = parser.parse_args(argv)
    if args.command == 'version':
        print(__version__)
        return 0
    if args.command == 'routes':
        print(json.dumps(list_routes(), ensure_ascii=False, indent=2))
        return 0
    if args.command == 'generate-skill':
        package = generate_chatgpt_skill(args.output_dir, force=args.force)
        print(str(package))
        return 0
    if args.command == 'create':
        print(new_run_id())
        return 0
    if args.command in ('status', 'cancel', 'events'):
        return _host_command(args)
    if args.command == 'inspect':
        try:
            report = inspect_run(args.event_log, args.run_id)
        except InspectError as exc:
            print(f"atlas inspect: {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print(render_inspection(report), end='')
        return 0
    if args.command == 'run':
        if args.run_id is not None:
            if not args.event_log:
                run_p.error('--run-id requires --event-log')
            try:
                validate_run_id(args.run_id)
            except ValueError as exc:
                run_p.error(str(exc))
        if bool(args.mqobsidian_path) != bool(args.mq_project):
            run_p.error('--mqobsidian-path and --mq-project must be used together')
        # Memory and the historical unbounded behaviour demand explicit opt-in.
        if not args.unsafe_legacy_unbounded and (args.memory_dir or args.mqobsidian_path):
            run_p.error('memory output requires --unsafe-legacy-unbounded')
        # Before the worker hop: a usage error inside the worker would reach
        # the parent as an unreadable result instead of as a usage error.
        if (args.repo_path and not args.unsafe_legacy_unbounded
                and not Path(args.repo_path).expanduser().is_dir()):
            run_p.error(f'--repo-path is not a directory: {args.repo_path}')
        if argv is None and not args.unsafe_legacy_unbounded:
            return _run_hard_cli(args)
        memory_adapter = None
        if args.mqobsidian_path:
            memory_adapter = MQObsidianMemoryAdapter(args.mqobsidian_path, project=args.mq_project)
        controller = AtlasController(
            max_iterations=args.max_iterations,
            memory_dir=args.memory_dir,
            memory_adapter=memory_adapter,
            events=JsonlSink(args.event_log) if args.event_log else None,
        )
        cancelled = (
            cancel_requested(args.event_log, args.run_id) if args.run_id else None
        )
        if args.unsafe_legacy_unbounded:
            observations: list[str] = []
            if args.repo_path:
                observations.extend(FilesystemRepoAdapter(args.repo_path).observe(args.task))
            if args.repo:
                observations.extend(GitHubRepoAdapter(args.repo, ref=args.repo_ref).observe(args.task))
            run = _start(lambda: controller.run(
                args.task, observations=observations, json_mode=True,
                run_id=args.run_id, cancelled=cancelled,
                one_run_per_log=bool(args.event_log),
            ))
        else:
            readers: list[Callable[[str, RunBudget], list[str]]] = []
            evidence: EvidenceBase | None = None
            observer: FilesystemRepoObserver | None = None
            if args.repo_path:
                # Evidence, not prose: an empty base bound to one snapshot, and
                # the observer reads into it inside the run, on the run's budget.
                evidence = EvidenceBase(take_snapshot(args.repo_path))
                observer = FilesystemRepoObserver(args.repo_path)
            if args.repo:
                github_adapter = GitHubRepoAdapter(args.repo, ref=args.repo_ref)
                def read_github(task: str, budget: RunBudget) -> list[str]:
                    return github_adapter.observe(task, budget=budget)
                readers.append(read_github)
            limits = RunLimits(
                wall_seconds=args.wall_seconds, model_calls=0,
                tool_calls=args.max_tool_calls, tokens=0,
                output_bytes=args.max_output_bytes,
            )
            run = _start(lambda: controller.run(
                args.task, readers=readers, evidence=evidence, observer=observer,
                read_first=observer is not None, limits=limits, json_mode=True,
                run_id=args.run_id, cancelled=cancelled,
                one_run_per_log=bool(args.event_log),
            ))
        if run is None:
            return 1
        return _print_run(run, json_mode=args.json)
    return 1

if __name__ == '__main__':
    raise SystemExit(main())
