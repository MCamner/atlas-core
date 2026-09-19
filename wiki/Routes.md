# Routes

Routes are the first layer of structure in Atlas Core.

A route classifies the task and selects the smallest useful method for the loop.

## Current route idea

Atlas Core uses deterministic route selection by default. That is intentional: the loop stays testable without a live LLM provider. Execution can be delegated to a model adapter; routing stays deterministic.

Expected route families:

- repo review
- architecture decision
- root cause analysis
- decision tradeoff
- learning or explanation
- prompt improvement
- general task

## Route contract

A route should define:

```text
name
purpose
when to use
inputs
steps
stop conditions
safety notes
```

## Good routing behavior

Atlas should prefer:

- minimal sufficient route
- clear plan over broad analysis
- read-only observation before write actions
- evaluation before retry
- explicit uncertainty over invented certainty

## Bad routing behavior

Avoid:

- running every method just because it exists
- selecting a route and then stopping without execution
- hiding risky write actions inside generic execution
- treating memory or MQ as mandatory
- continuing after max iterations without a reason

## Example

Task:

```text
granska MCamner/mqobsidian och hitta P0/P1/P2 förbättringar
```

Expected route:

```text
repo review
```

Expected behavior:

```text
observe repo → classify docs/runtime boundary → identify P0/P1/P2 → evaluate confidence → final recommendation
```

## Rule

```text
Route first, but do not stop at routing.
```
