from __future__ import annotations
import argparse, json
from . import __version__
from .controller import AtlasController
from .router import list_routes
from .adapters.filesystem_repo import FilesystemRepoAdapter
from .adapters.github_reader import GitHubRepoAdapter

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="atlas", description="Atlas Core loop engine")
    sub = parser.add_subparsers(dest="command", required=True)
    run_p = sub.add_parser("run", help="Run Atlas loop for a task")
    run_p.add_argument("task", help="Task to run")
    run_p.add_argument("--max-iterations", type=int, default=2, help="Max loop iterations")
    run_p.add_argument("--memory-dir", default=None, help="Optional local memory output directory")
    run_p.add_argument("--json", action="store_true", help="Print full run state as JSON")
    run_p.add_argument("--repo", default=None, help="Optional GitHub repo in owner/name form to observe before running")
    run_p.add_argument("--repo-ref", default=None, help="Optional branch/ref for --repo")
    run_p.add_argument("--repo-path", default=None, help="Optional local repo path to observe before running")
    sub.add_parser("routes", help="List available routes")
    sub.add_parser("version", help="Show version")
    args = parser.parse_args(argv)
    if args.command == "version":
        print(__version__)
        return 0
    if args.command == "routes":
        print(json.dumps(list_routes(), ensure_ascii=False, indent=2))
        return 0
    if args.command == "run":
        controller = AtlasController(max_iterations=args.max_iterations, memory_dir=args.memory_dir)
        observations = []
        if args.repo_path:
            observations.extend(FilesystemRepoAdapter(args.repo_path).observe(args.task))
        if args.repo:
            observations.extend(GitHubRepoAdapter(args.repo, ref=args.repo_ref).observe(args.task))
        result = controller.run(args.task, observations=observations, json_mode=args.json)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(result)
        return 0
    return 1

if __name__ == "__main__":
    raise SystemExit(main())
