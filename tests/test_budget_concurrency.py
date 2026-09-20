from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import threading
import unittest

from atlas_core.budget import BudgetExceeded, RunBudget, RunCancelled, RunLimits


class TestConcurrentBudget(unittest.TestCase):
    def test_concurrent_nested_tools_share_atomic_limit(self) -> None:
        budget = RunBudget(RunLimits(10, 1, 7, 100, 1000))
        barrier = threading.Barrier(24)
        def attempt(_idx: int) -> bool:
            barrier.wait()
            try:
                budget.reserve_tool()
            except BudgetExceeded:
                return False
            return True
        with ThreadPoolExecutor(max_workers=24) as workers:
            outcomes = list(workers.map(attempt, range(24)))
        self.assertEqual(sum(outcomes), 7)
        self.assertEqual(budget.tool_calls, 7)

    def test_cancellation_before_any_model_or_tool(self) -> None:
        event = threading.Event()
        b = RunBudget(RunLimits(10, 2, 2, 100, 100), cancelled=event.is_set)
        event.set()
        with self.assertRaises(RunCancelled):
            b.reserve_model()
        with self.assertRaises(RunCancelled):
            b.reserve_tool()
        self.assertEqual(b.model_calls, 0)
        self.assertEqual(b.tool_calls, 0)


if __name__ == '__main__':
    unittest.main()
