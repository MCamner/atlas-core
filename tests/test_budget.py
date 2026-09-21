from __future__ import annotations

import unittest
from typing import Any

from atlas_core.budget import BudgetExceeded, RunBudget, RunLimits, UnmeteredUsage


def limits(**changes: object) -> RunLimits:
    fields: dict[str, Any] = dict(wall_seconds=10.0, model_calls=2, tool_calls=2, tokens=5, output_bytes=4)
    fields.update(changes)
    return RunLimits(**fields)


class TestBudgetAccounting(unittest.TestCase):
    def test_invalid_limits_fail_closed(self):
        for value in (0, -1, float('inf'), float('nan'), True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                limits(wall_seconds=value)
        for field in ('model_calls', 'tool_calls', 'tokens', 'output_bytes'):
            with self.subTest(field=field), self.assertRaises(ValueError):
                limits(**{field: True})

    def test_monotonic_deadline_and_no_incall_timeout_claim(self):
        now = [10.0]
        budget = RunBudget(limits(wall_seconds=3), clock=lambda: now[0])
        budget.check()
        now[0] = 13.0
        with self.assertRaisesRegex(BudgetExceeded, 'wall_seconds'):
            budget.check()

    def test_calls_include_retries_and_nested_tools(self):
        budget = RunBudget(limits())
        budget.reserve_model()
        budget.reserve_model()
        with self.assertRaisesRegex(BudgetExceeded, 'model_calls'):
            budget.reserve_model()
        budget.reserve_tool()
        budget.reserve_tool()
        with self.assertRaisesRegex(BudgetExceeded, 'tool_calls'):
            budget.reserve_tool()
        self.assertEqual(budget.model_calls, 2)
        self.assertEqual(budget.tool_calls, 2)

    def test_tokens_are_reported_not_guessed(self) -> None:
        budget = RunBudget(limits())
        for usage in (None, -1, '3', True):
            invalid: Any = usage  # deliberately malformed external adapter data
            with self.subTest(usage=usage), self.assertRaises(UnmeteredUsage):
                budget.charge_tokens(invalid)
        budget.charge_tokens(3)
        with self.assertRaisesRegex(BudgetExceeded, 'tokens'):
            budget.charge_tokens(3)

    def test_output_budget_counts_utf8_bytes_across_retries(self):
        budget = RunBudget(limits(output_bytes=5))
        budget.charge_output('ö')
        budget.charge_output('ö')
        with self.assertRaisesRegex(BudgetExceeded, 'output_bytes'):
            budget.charge_output('ö')
        self.assertEqual(budget.output_bytes, 6)


if __name__ == '__main__':
    unittest.main()
