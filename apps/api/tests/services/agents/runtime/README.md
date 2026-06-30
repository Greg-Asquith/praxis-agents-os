<!-- apps/api/tests/services/agents/runtime/README.md -->
# Agent Runtime Tests

Tests for the Pydantic AI agent runtime under `services/agents/runtime/`.

`test_pydantic_ai_spike.py` is build-sequence step 1 from
`docs/architecture/agent-runtime.md`: it pins the pydantic-ai behaviours the runtime
design depends on (message serialization, the streaming driver, and deferred-tool
approval/resume) against the installed version. It is deterministic and provider-free
(`TestModel`), so it runs without a database or model credentials.
