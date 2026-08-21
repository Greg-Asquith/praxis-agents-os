<!-- apps/api/tests/services/agents/runtime/README.md -->

# Agent runtime tests

Tests for the Pydantic AI agent runtime under `services/agents/runtime/`.

The `test_pydantic_ai_spike.py` file implements the first build-sequence step
from `docs/architecture/agent-runtime.md`. It checks the Pydantic AI behavior
that the runtime depends on: message serialization, streaming, and deferred
tool approval and resumption. The test uses `TestModel`, so it runs without a
database, provider, or model credentials.
