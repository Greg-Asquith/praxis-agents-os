# Historical approval fixtures

These synthetic records were captured on 8 September 2026 from an isolated
checkout of `a6530950`, before the delegation reliability changes. They use
Pydantic AI 2.28.0 and Monty 0.0.21. They contain only scenario prompts,
random test identities, and synthetic tool results. No provider was contacted.

The saved records cover these states:

- `direct.json`: one external write awaiting approval
- `workflow.json`: the first write in a two-write workflow
- `workflow-second.json`: the second approval, retaining the first completed
  write and its real interpreter snapshot
- `delegated.json`: a root and specialist parked on the specialist's workflow
- `staged.json`: a workflow with `write_file` content staged for approval;
  the staged object contains exactly the UTF-8 bytes `nested body`

Capture used the old runtime's `run_scenario` and `scripted_model` helpers,
`runtime_tool` registration, and `persist_suspended_run` serializer. The
synthetic external tool is `scenario_release_write(value: str)`. Its workflow
calls it with `first`, then `second`. The old standalone workflow resume helper
produced the second-round fixture after the first write settled. The delegated
fixture uses the old `delegate_to_agent` runtime. The staged fixture uses the
old `write_file` staging implementation and local test storage.

`tests/support/approval_fixtures.py` rebinds database identities to a fresh
scenario workspace and refreshes lifecycle timestamps. It preserves the
serialized consent, message history, and interpreter bytes. Tests restore the
synthetic staged object under its rebound owner reference. Keep these saved
bytes when changing serializers; regenerating them with the current runtime
would erase their upgrade coverage.

The upgrade scenarios also mutate copies to represent unsupported versions,
ambiguous histories, terminal children, and stale tabs. Running state with a
retained approval but no reservation represents the old acceptance boundary:
the old service committed the lease before passing in-memory decisions to its
worker. That interrupted state must retain blocked recovery evidence.
