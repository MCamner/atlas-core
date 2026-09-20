"""One-time guarded CLI edit; remove after integration."""
from pathlib import Path
p=Path('atlas_core/cli.py')
s=p.read_text(encoding='utf-8')
def replace(old: str,new: str,count: int=1)->None:
    global s
    assert s.count(old)==count, (s.count(old),old[:120])
    s=s.replace(old,new)
replace('from __future__ import annotations\nimport argparse, json\n', '''from __future__ import annotations
import argparse, json
from typing import Callable
from .budget import RunBudget, RunLimits
''')
replace('    run_p.add_argument("--max-iterations", type=int, default=2, help="Max loop iterations")\n', '''    run_p.add_argument("--max-iterations", type=int, default=2, help="Max loop iterations")
    run_p.add_argument("--wall-seconds", type=float, default=30.0, help="Cooperative wall-clock limit (default 30s)")
    run_p.add_argument("--max-tool-calls", type=int, default=32, help="Shared observation/tool call limit")
    run_p.add_argument("--max-output-bytes", type=int, default=65536, help="Combined observation/output UTF-8 limit")
    run_p.add_argument("--unsafe-legacy-unbounded", action="store_true", help="Explicitly opt into legacy unmetered mode and memory output")
''')
replace('''        memory_adapter = None
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
''', '''        # The regular CLI has a bounded, read-only execution path. Explicit
        # external-memory writes and the historical unbounded behaviour require
        # an unmistakable opt-in; they are not represented as a bounded run.
        if not args.unsafe_legacy_unbounded and (args.memory_dir or args.mqobsidian_path):
            run_p.error("memory output requires --unsafe-legacy-unbounded")
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
''')
p.write_text(s,encoding='utf-8')
