# Customize

The sample intentionally keeps the domain logic in one file:
[src/tools/policy_review_tools.py](../src/tools/policy_review_tools.py).

## Change required documents

Edit `REQUIRED_DOCUMENTS`, then update the example request. The report lists any type
in this collection without a received document as missing.

## Read real documents

`inspect_driver_document` currently maps message metadata to a simple evidence state.
To connect a document system, replace that mapping with an approved lookup while
keeping the function:

- synchronous
- JSON serializable
- free of policy decisions
- safe to retry

## Change the report

`build_driver_review_report` creates the HTML. Adjust its markup or add
decision-neutral fields, but keep:

- `review_status: human_review_required`
- `decision: null`
- a clear instruction that a person must verify the source documents

## Change the workflow

The planning instructions are in [src/main.agent.md](../src/main.agent.md). The current
plan is validate, inspect in parallel, build, and publish.

A new workflow activity should be a synchronous function decorated with
`@workflow_tool`. Give its description clear input and output contracts. Make any side
effects idempotent because durable activities can be retried.

Redeploy code changes with:

```bash
azd deploy
```

Next: [How it works](how-it-works.md) | [Try variations](use-cases.md) |
[Deploy](deploy.md)
