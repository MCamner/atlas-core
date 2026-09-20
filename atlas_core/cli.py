from __future__ import annotations
import argparse, json, sys
from typing import Callable, Literal
from .budget import RunBudget, RunLimits
from . import __version__
from .controller import AtlasController
from .router import list_routes
from .adapters.filesystem_repo import FilesystemRepoAdapter
from .adapters.github_reader import GitHubRepoAdapter
from .adapters.mqobsidian import MQObsidianMemoryAdapter
from .skill_generator import generate_chatgpt_skill
from .finalizer import render_run_text
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


def _worker_failure(
    args: argparse.Namespace, *,
    reason: Literal['budget_exhausted', 'tool_error', 'cancelled'],
    detail: str, error: str,
) -> dict:
    # The worker may be stuck or have been killed. Never synthesize a graded
    # answer, old evaluations, or a successful run from its partial stdout.
    state = AtlasRunState(task=args.task, max_iterations=args.max_iterations)
    state.enter('observing')
    if reason == 'budget_exhausted':
        state.metadata['budget_exhausted'] = detail
    else:
        state.metadata['failure'] = {
            'stage': 'cli_worker', 'error': error, 'message': detail[:512],
        }
    state.stop(reason)
    return state.to_dict()


def _run_hard_cli(args: argparse.Namespace) -> int:
    # Only the *public* CLI entrypoint (`main()` with argv=None) takes this
    # outer boundary. Embedded `main([...])` and `AtlasController.run()` are
    # in-process APIs and retain their documented cooperative contract.
    limits = RunLimits(
        wall_seconds=args.wall_seconds, model_calls=0,
        tool_calls=args.max_tool_calls, tokens=0,
        output_bytes=args.max_output_bytes,
    )
    command = [sys.executable, '-m', 'atlas_core.worker_cli', *sys.argv[1:], '--json']
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
    run_p.add_argument('--repo-path', default=None, help='Optional local repo path to observe before running')
    run_p.add_argument('--mqobsidian-path', default=None, help='Optional mqobsidian vault path')
    run_p.add_argument('--mq-project', default=None, help='Project name for mqobsidian context')
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
    if args.command == 'run':
        if bool(args.mqobsidian_path) != bool(args.mq_project):
            run_p.error('--mqobsidian-path and --mq-project must be used together')
        # Memory and the historical unbounded behaviour demand explicit opt-in.
        if not args.unsafe_legacy_unbounded and (args.memory_dir or args.mqobsidian_path):
            run_p.error('memory output requires --unsafe-legacy-unbounded')
        if argv is None and not args.unsafe_legacy_unbounded:
            return _run_hard_cli(args)
        memory_adapter = None
        if args.mqobsidian_path:
            memory_adapter = MQObsidianMemoryAdapter(args.mqobsidian_path, project=args.mq_project)
        controller = AtlasController(
            max_iterations=args.max_iterations,
            memory_dir=args.memory_dir,
            memory_adapter=memory_adapter,
        )
        if args.unsafe_legacy_unbounded:
            observations: list[str] = []
            if args.repo_path:
                observations.extend(FilesystemRepoAdapter(args.repo_path).observe(args.task))
            if args.repo:
                observations.extend(GitHubRepoAdapter(args.repo, ref=args.repo_ref).observe(args.task))
            run = controller.run(args.task, observations=observations, json_mode=True)
        else:
            readers: list[Callable[[str, RunBudget], list[str]]] = []
            if args.repo_path:
                local_adapter = FilesystemRepoAdapter(args.repo_path)
                def read_local(task: str, budget: RunBudget) -> list[str]:
                    return local_adapter.observe(task, budget=budget)
                readers.append(read_local)
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
            run = controller.run(args.task, readers=readers,
                                 limits=limits, json_mode=True)
        return _print_run(run, json_mode=args.json)
    return 1

if __name__ == '__main__':
    raise SystemExit(main())
