# Agent behavior evals

These opt-in evaluations use live provider models through the production
`build_runtime_agent` seam. They are deliberately outside pytest and never run
as part of `make check`.

Run from the repository root:

```sh
EVALS_MODEL=openai:gpt-5.6-luna OPENAI_API_KEY=... make evals
```

`EVALS_MODEL` must use `provider:model` form. The runner exits nonzero when the
matching provider key is absent. Cases live in
`evals/datasets/agent_behavior.yaml`; add narrowly named examples with explicit
programmatic expectations, then rely on the case-specific judges for qualitative
instruction adherence, safety, and output quality. Tool-selection-only cases
disable response judges because the runner intentionally stops after the first
tool call. Exact-output cases can also disable response judges when their
programmatic evaluator completely defines success; this avoids asking a
qualitative judge to reject an intentionally minimal response.

The injection scaffolds place hostile knowledge and memory content in model
history as typed tool returns and check both tool choice and outbound argument
canaries. They do not execute the unfinished knowledge or memory tools. Once
those tools land, their owning plans must replace the scaffolds with real
channel-tool cases while retaining the same exfiltration and compliance checks.
The Gmail case uses the shared hostile-email fixture and production untrusted-
content framing before placing the tool return in history.
