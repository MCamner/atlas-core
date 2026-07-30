# Atlas Core Architecture

Atlas Core is a small bounded state machine:

```text
NEW_TASK -> OBSERVING -> ROUTING -> PLANNING -> EXECUTING -> EVALUATING -> DONE
```

Retry path:

```text
EVALUATING -> REPLANNING -> EXECUTING
```

Approval path:

```text
EVALUATING -> NEED_USER_APPROVAL
```

Core components:

- controller.py — loop coordinator
- router.py — deterministic route selector
- planner.py — builds the execution plan
- executor.py — route-specific execution
- evaluator.py — quality gates and retry decision
- memory.py — optional memory candidate creation
- safety.py — write-action detection
- finalizer.py — final response

Adapter rule: Atlas Core does not depend on MQ, GitHub, Obsidian, or ChatGPT.
