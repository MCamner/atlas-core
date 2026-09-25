"""Platform-lock boundary: importing Atlas does not itself require POSIX fcntl."""
from __future__ import annotations

from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from atlas_core.cli import main
from atlas_core import eventlog, host_api
from atlas_core.eventlog import LockUnavailable, RunLock


class TestWithoutFcntl(unittest.TestCase):
    def test_cli_module_imports_when_atlas_modules_cannot_import_fcntl(self) -> None:
        code = r"""
import builtins
real_import = builtins.__import__
def guarded(name, globals=None, locals=None, fromlist=(), level=0):
    caller = (globals or {}).get("__name__", "")
    if name == "fcntl" and caller.startswith("atlas_core"):
        raise ImportError("simulated non-POSIX platform")
    return real_import(name, globals, locals, fromlist, level)
builtins.__import__ = guarded
import atlas_core.cli
print("imported")
"""
        result = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "imported")

    def test_lock_operations_fail_closed_without_fcntl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lock = Path(tmp) / "run.lock"
            with mock.patch.object(eventlog, "fcntl", None):
                with self.assertRaises(LockUnavailable):
                    RunLock(lock).acquire()
                self.assertFalse(lock.exists())
            with mock.patch.object(host_api, "fcntl", None):
                with self.assertRaises(LockUnavailable):
                    host_api.is_locked(Path(tmp) / "events.jsonl", "run-1")

    def test_status_reports_lock_unavailable_instead_of_crashing(self) -> None:
        err = StringIO()
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(host_api, "fcntl", None), redirect_stderr(err):
            code = main([
                "status", "run-1", "--event-log", str(Path(tmp) / "events.jsonl"),
            ])
        self.assertEqual(code, 1)
        self.assertIn("requires POSIX fcntl", err.getvalue())


if __name__ == "__main__":
    unittest.main()
