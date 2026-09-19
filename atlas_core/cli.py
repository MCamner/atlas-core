from __future__ import annotations
import argparse, json
from . import __version__
from .controller import AtlasController
from .router import list_routes
from .adapters.filesystem_repo import FilesystemRepoAdapter
from .adapters.github_reader import GitHubRepoAdapter
from .adapters.mqobsidian import MQObsidianMemoryAdapter
from .skill_generator import generate_chatgpt_skill
from .finalizer import render_run_text

# A caller has to be able to tell "passed" from "gave up" without reading prose.
# Every stop reason declared in state.StopReason must appear here; a test
# enforces that, so adding a stop reason forces a decision about its code.
EXIT_CODES: dict[str, int] = {
    "passed": 0,
    "failed": 1,
    "no_actionable_retry": 2,
    "max_iterations": 2,
    "approval_required": 3,
}
UNKNOWN_STOP_REASON_EXIT = 1

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
    run_p.add_argument("--mqobsidian-path", default=None, help="Optional mqobsidian vault path")
    run_p.add_argument("--mq-project", default=None, help="Project name for mqobsidian context")
    skill_p = sub.add_parser("generate-skill", help="Generate a ChatGPT Skill package")
    skill_p.add_argument("output_dir", help="Parent directory for the generated skill")
    skill_p.add_argument("--force", action="store_true", help="Overwrite generated skill files")
    sub.add_parser("routes", help="List available routes")
    sub.add_parser("version", help="Show version")
    args = parser.parse_args(argv)
    if args.command == "version":
        print(__version__)
        return 0
    if args.command == "routes":
        print(json.dumps(list_routes(), ensure_ascii=False, indent=2))
        return 0
    if args.command == "generate-skill":
        package = generate_chatgpt_skill(args.output_dir, force=args.force)
        print(str(package))
        return 0
    if args.command == "run":
        if bool(args.mqobsidian_path) != bool(args.mq_project):
            run_p.error("--mqobsidian-path and --mq-project must be used together")
        memory_adapter = None
        if args.mqobsidian_path:
            memory_adapter = MQObsidianMemoryAdapter(args.mqobsidian_path, project=args.mq_project)
        controller = AtlasController(
            max_iterations=args.max_iterations,
            memory_dir=args.memory_dir,
            memory_adapter=memory_adapter,
        )
        observations = []
        if args.repo_path:
            observations.extend(FilesystemRepoAdapter(args.repo_path).observe(args.task))
        if args.repo:
            observations.extend(GitHubRepoAdapter(args.repo, ref=args.repo_ref).observe(args.task))
        # Always take the run document: the exit code comes from stop_reason,
        # and the text form is rendered from the same document.
        run = controller.run(args.task, observations=observations, json_mode=True)
        if args.json:
            print(json.dumps(run, ensure_ascii=False, indent=2))
        else:
            print(render_run_text(run))
        return EXIT_CODES.get(run.get("stop_reason") or "", UNKNOWN_STOP_REASON_EXIT)
    return 1

if __name__ == "__main__":
    raise SystemExit(main())
