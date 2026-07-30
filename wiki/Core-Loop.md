# Core Loop

Atlas Core is built around one bounded loop:

```text
observe → route → plan → execute → evaluate → retry/replan → finalize
```

The loop is not meant to run forever. Every run must move toward a useful final answer or stop with a clear reason.

## Stages

### 1. Observe

Collect task context.

Examples:

- task text
- local repo summary
- public GitHub repo observations
- optional memory candidates
- route map

The core should not assume MQ, Obsidian, GitHub, or ChatGPT exist. Those are adapters.

### 2. Route

Select the smallest useful route for the task.

A route should answer:

```text
What kind of work is this?
Which method should run first?
What should not be attempted?
```

### 3. Plan

Create a small execution plan.

A good plan is short, concrete, and testable.

### 4. Execute

Run the selected method.

In v0.2.0, execution is rule-based. Live model execution belongs in a future model adapter.

### 5. Evaluate

Check whether the result is good enough.

Evaluation can decide:

- finish
- retry
- replan
- ask for approval
- request more context
- stop because the task is unsafe or under-specified

### 6. Retry / Replan

Retry only when it is useful and bounded.

The loop must not hide repeated failure behind more output.

### 7. Finalize

Return the best current answer with caveats and next action.

## Stop rules

Atlas Core should stop when:

- the result satisfies the task
- max iterations are reached
- a write action needs explicit approval
- required context is missing
- the task is outside the available adapter surface

## Design principle

```text
A loop is only useful if it knows when to stop.
```
