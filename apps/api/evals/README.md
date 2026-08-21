# Agent behavior evaluations

These optional evaluations exercise the same agent runtime used by the system,
using live provider models and the configured embedding provider. They check
behavior that deterministic tests cannot judge well, including instruction
following, tool choice, and resistance to hostile external content. Because
they use paid model APIs, they stay outside pytest and never run as part of
`make check`.

From the repository root, run the live-model evaluations:

```sh
EVALS_MODEL=openai:gpt-5.6-luna OPENAI_API_KEY=... make evals
```

`EVALS_MODEL` must use `provider:model` form. The runner exits nonzero when the
matching model key or configured embedding credential is absent, or when the
live memory calibration violates its pinned threshold invariants. Cases live in
`evals/datasets/agent_behavior.yaml`; add narrowly named examples with explicit
programmatic expectations, then rely on the case-specific judges for qualitative
instruction adherence, safety, and output quality. Tool-selection-only cases
disable response judges because the runner intentionally stops after the first
tool call. Exact-output cases can also disable response judges when their
programmatic evaluator completely defines success; this avoids asking a
qualitative judge to reject an intentionally minimal response.

The injection scaffolds place hostile external knowledge and provider content
in model history as typed tool returns and check both tool choice and outbound
argument canaries. Internal memory is trusted agent state and is deliberately
excluded from untrusted-content framing and injection-warning evaluations. The
Gmail case uses the shared hostile-email fixture and production untrusted-
content framing before placing the tool return in history.
The code-mode case uses the shared hostile workflow-result fixture and the
production `code_mode_workflow` provenance frame; it verifies that the
consuming model reports the embedded instruction without selecting an external
write or copying the attacker's canary into tool arguments.
