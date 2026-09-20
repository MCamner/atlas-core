"""The public CLI must not rely on a synchronous handler cooperating."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from atlas_core.process_guard import (
    WorkerDeadlineExceeded, WorkerOutputExceeded, run_bounded_process,
)


@unittest.skipUnless(os.name == 'posix', 'POSIX process-group guard')
class TestHardCliDeadline(unittest.TestCase):
    def test_noncooperating_worker_is_killed_at_deadline(self) -> None:
        started = time.monotonic()
        with self.assertRaises(WorkerDeadlineExceeded):
            run_bounded_process(
                [sys.executable, '-c', 'import time; time.sleep(30)'],
                timeout=0.12, stdout_limit=1024,
            )
        self.assertLess(time.monotonic() - started, 3.0)

    def test_descendant_holding_pipes_open_is_killed(self) -> None:
        script = (
            'import subprocess,sys; '
            'subprocess.Popen([sys.executable,"-c","import time;time.sleep(30)"]); '
            'sys.stdout.write("started\\n");sys.stdout.flush()'
        )
        started = time.monotonic()
        with self.assertRaises(WorkerDeadlineExceeded):
            run_bounded_process(
                [sys.executable, '-c', script],
                timeout=0.2, stdout_limit=1024,
            )
        self.assertLess(time.monotonic() - started, 3.0)

    def test_unbounded_stdout_cannot_grow_parent_buffer(self) -> None:
        with self.assertRaises(WorkerOutputExceeded) as caught:
            run_bounded_process(
                [sys.executable, '-c', 'import os;os.write(1,b"x"*1000000)'],
                timeout=2, stdout_limit=1024,
            )
        self.assertEqual(str(caught.exception), 'stdout')

    def test_child_exit_status_is_not_silently_promoted(self) -> None:
        result = run_bounded_process(
            [sys.executable, '-c', 'import sys;sys.exit(9)'],
            timeout=2, stdout_limit=1024,
        )
        self.assertEqual(result.returncode, 9)

    def test_public_cli_normal_repo_run_uses_worker_and_returns_document(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'README.md').write_text('# Real source\n', encoding='utf-8')
            result = subprocess.run(
                [sys.executable, '-m', 'atlas_core.cli', 'run',
                 'review repo', '--repo-path', tmp, '--wall-seconds', '10', '--json'],
                capture_output=True, text=True, timeout=15,
            )
        document = json.loads(result.stdout)
        self.assertIn('budget_usage', document['metadata'])
        self.assertTrue(any('README.md' in item for item in document['observations']))
        self.assertEqual(document['memory_candidates'], [])
        self.assertEqual(result.returncode, 2 if document['stop_reason'] != 'passed' else 0)

    def test_public_cli_rejects_worker_that_cannot_start_in_time(self) -> None:
        started = time.monotonic()
        result = subprocess.run(
            [sys.executable, '-m', 'atlas_core.cli', 'run', 'review',
             '--wall-seconds', '0.000001', '--json'],
            capture_output=True, text=True, timeout=10,
        )
        document = json.loads(result.stdout)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(document['stop_reason'], 'budget_exhausted')
        self.assertEqual(document['metadata']['budget_exhausted'], 'wall_seconds')
        self.assertEqual(document['evaluations'], [])
        self.assertLess(time.monotonic() - started, 5.0)


if __name__ == '__main__':
    unittest.main()
