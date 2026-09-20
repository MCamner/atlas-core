from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import time
import unittest
from typing import Any
from unittest.mock import patch
from urllib.error import URLError

from atlas_core.budget import RunBudget, RunLimits
from atlas_core.cli import main
from atlas_core.controller import AtlasController


def run_cli(args: list[str]) -> tuple[int, dict[str, Any]]:
    output = StringIO()
    with redirect_stdout(output):
        code = main(['run', 'review repository', '--json', *args])
    return code, json.loads(output.getvalue())


class TestBoundedCLI(unittest.TestCase):
    def test_bounded_cli_reads_real_file_with_shared_usage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'README.md').write_text('# sample\ncheck code', encoding='utf-8')
            code, result = run_cli(['--repo-path', tmp])
        self.assertEqual(result['metadata']['budget_usage']['tool_calls'], 1)
        self.assertTrue(any('README.md' in item for item in result['observations']))
        self.assertEqual(result['memory_candidates'], [])
        self.assertIn('budget_usage', result['metadata'])
        self.assertIn(code, (0, 2, 3))

    def test_zero_tools_fails_before_reading(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'README.md').write_text('hello', encoding='utf-8')
            code, result = run_cli(['--repo-path', tmp, '--max-tool-calls', '0'])
        self.assertEqual(code, 2)
        self.assertEqual(result['stop_reason'], 'budget_exhausted')
        self.assertEqual(result['metadata']['budget_exhausted'], 'tool_calls')
        self.assertEqual(result['evaluations'], [])

    def test_network_failure_cannot_become_fallback_pass(self) -> None:
        with patch('atlas_core.adapters.github_reader.GitHubRepoAdapter._request',
                   side_effect=URLError('network unavailable')):
            code, result = run_cli(['--repo', 'example/project'])
        self.assertEqual(code, 1)
        self.assertEqual(result['stop_reason'], 'tool_error')
        self.assertEqual(result['metadata']['failure']['stage'], 'observer')
        self.assertEqual(result['evaluations'], [])

    def test_output_limit_includes_readme_before_executor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'README.md').write_text('x' * 200, encoding='utf-8')
            code, result = run_cli(['--repo-path', tmp, '--max-output-bytes', '10'])
        self.assertEqual(code, 2)
        self.assertEqual(result['stop_reason'], 'budget_exhausted')
        self.assertEqual(result['metadata']['budget_exhausted'], 'output_bytes')
        self.assertEqual(result['evaluations'], [])

    def test_memory_side_effect_requires_explicit_legacy_optin(self) -> None:
        with self.assertRaises(SystemExit) as caught, patch('sys.stderr'):
            main(['run', 'hej', '--memory-dir', '/tmp/atlas-test'])
        self.assertEqual(caught.exception.code, 2)

    def test_invalid_limits_do_not_run(self) -> None:
        with self.assertRaises(ValueError):
            main(['run', 'hej', '--wall-seconds', '-1'])

    def test_slow_reader_stops_before_grading(self) -> None:
        def slow(_task: str, budget: RunBudget) -> list[str]:
            time.sleep(.02)
            budget.check()
            return ['not observed']
        result = AtlasController().run('read', readers=[slow], json_mode=True,
            limits=RunLimits(.001, model_calls=0, tool_calls=1, tokens=0, output_bytes=100))
        self.assertEqual(result['stop_reason'], 'budget_exhausted')
        self.assertEqual(result['evaluations'], [])
        self.assertEqual(result['memory_candidates'], [])

    def test_readers_require_explicit_budget(self) -> None:
        with self.assertRaisesRegex(ValueError, 'require RunLimits'):
            AtlasController().run('read', readers=[lambda _t, _b: []], json_mode=True)


if __name__ == '__main__':
    unittest.main()
