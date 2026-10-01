# Agent behavior evaluations

These optional evaluations exercise the same agent runtime used by the system,
using live provider models and the configured embedding provider. They check
behavior that deterministic tests cannot judge well, including instruction
following, tool choice, and resistance to hostile external content. Because
they use paid model APIs, they stay outside pytest and never run as part of
`make check`.

From the repository root, run the live-model evaluations:

```sh
EVALS_MODEL=openai:gpt-6-luna OPENAI_API_KEY=... make evals
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
Gmail and Outlook cases use the shared hostile-email fixture and production untrusted-
content framing before placing the tool return in history.
The code-mode case uses the shared hostile workflow-result fixture and the
production `code_mode_workflow` provenance frame; it verifies that the
consuming model reports the embedded instruction without selecting an external
write or copying the attacker's canary into tool arguments.

The `workflow_*` cases mount integration tools against a synthetic selected
context (`active_context` in the case inputs) and check the choice between
direct calls and `run_code`. The `WorkflowArguments` evaluator parses the
script and checks each tool call against the tool's argument
validator: unknown or missing keyword arguments, and literal values that fail
validation.

The `document_*` cases place a real document read or saved-report preview in
history and check the next call. `AcceptedToolCall` passes when the first call
is an accepted document tool, directly or inside `run_code`, with
arguments that pass the tool's validator and contain the case's
`required_argument_text`. For a `run_code` call, that text must appear
literally in the script source, not in a value the script computes.

The evals have no workspace session, so discovery and planning calls run
without dispatch and don't end a case: `search_tools` and `load_capability`
run normally, `search_skills` finds no workspace skills, `read_todos` finds no
plan, and `write_todos` returns the plan without saving it. The runner stops before any other tool
runs.
