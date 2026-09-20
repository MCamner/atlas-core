"""One-time migration for an obsolete 'cancelled unreachable' assertion."""
from pathlib import Path
p = Path('tests/test_state_machine.py')
s = p.read_text(encoding='utf-8')
a = '''    NOT_YET_PRODUCED = {
        "cancelled": "P0.3 box four: abort",
    }
'''
b = '''    # Cancellation is produced by the controller's runtime checkpoints.
    NOT_YET_PRODUCED: dict[str, str] = {}
'''
assert s.count(a) == 1
s = s.replace(a, b)
a = '''            "budget_exhausted",
            "tool_error",
        }
'''
b = '''            "budget_exhausted",
            "tool_error",
            "cancelled",
        }
'''
assert s.count(a) == 1
p.write_text(s.replace(a, b), encoding='utf-8')
