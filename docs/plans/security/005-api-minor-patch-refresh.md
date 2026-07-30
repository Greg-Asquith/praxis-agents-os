# Plan 005: Refresh API minor and patch dependencies

## Status

- **Priority:** P2
- **Risk:** HIGH
- **Status:** TODO
- **Depends on:** Plan 004
- **Source:** Closed Dependabot PR #3

## Intent

Apply the API dependency refresh one package at a time, with additional gates
around the agent runtime and HTTP/provider boundaries. The closed grouped PR
could not reach tests because Ruff 0.16 introduced two new `RUF036` findings.

## Target versions

- `croniter` 6.2.2 → 6.2.4
- `fastapi` 0.138.1 → 0.141.1
- `greenlet` floor 3.3.0 → 3.5.4
- `httpx2` 2.5.0 → 2.9.1
- `logfire` 4.37.0 → 4.39.0
- `prometheus-client` 0.25.0 → 0.26.0
- `pydantic-ai` 2.1.0 → 2.20.0
- `tzdata` 2026.2 → 2026.3
- `uvicorn` 0.49.0 → 0.52.0
- `google-cloud-secret-manager` floor 2.20 → 2.30.0
- `google-cloud-storage` floor 2.18 → 3.13.0
- `boto3` floor 1.35 → 1.43.59
- `ruff` 0.15.19 → 0.16.0

If live `main` has drifted, use the smallest current minor/patch target and
record it.

The Google Cloud Storage manifest floor crosses a major-version boundary, but
the closed PR's lockfile was already resolving 3.12.0 and proposed 3.13.0.
Confirm that live `main` still resolves a 3.x version before treating this as a
minor refresh. Otherwise split it into a separately reviewed major upgrade.

## Update order and gates

1. Ruff. Resolve its two known findings by placing `None` last in the unions
   in:
   - `integrations/google_ads/tools/schemas.py`
   - `services/agents/runtime/untrusted.py`
   Do not suppress `RUF036`.
2. Low-coupling packages individually: `tzdata`, `greenlet`,
   `prometheus-client`, `logfire`.
3. Provider SDKs individually: Secret Manager, Cloud Storage, then boto3.
4. `croniter`, followed by all schedule tests.
5. FastAPI, followed by route, middleware, OpenAPI-contract, and SSE tests.
6. Uvicorn, followed by health, startup, SSE, and Docker smoke tests. Do not
   opt into experimental `zttp`; preserve the configured/default production
   protocol deliberately.
7. HTTPX2, followed by retry transport, integration provider, and external
   HTTP boundary tests.
8. Pydantic AI last, followed by the complete agent runtime scenarios and
   deterministic behavior-eval tests.

For each package:

- change only its declared floor;
- run `uv lock --upgrade-package <name>`;
- inspect both `pyproject.toml` and `uv.lock`;
- run the package-specific gate before moving on.

## STOP conditions

Stop and report if:

- uv upgrades another direct dependency outside the active unit;
- a provider begins reading implicit credentials or environment configuration;
- FastAPI changes route schemas, cookies, middleware ordering, SSE framing, or
  problem-detail responses unexpectedly;
- Uvicorn changes the selected HTTP/WebSocket implementation without an
  explicit repository decision;
- HTTPX2 changes retry, timeout, TLS, or proxy behaviour;
- Pydantic AI changes tool execution, approvals, deferred results, streaming,
  usage accounting, or native capability behaviour;
- fixing an update requires weakening a test, lint rule, permission boundary,
  or provider validation;
- deterministic tests pass but live eval quality regresses materially.

## Focused verification

```bash
cd apps/api
uv run ruff check .
uv run ruff format --check .
uv run pytest tests/services/agent_schedules tests/routes/schedules
uv run pytest tests/contract tests/middleware tests/routes/health
uv run pytest tests/services/agents/runtime tests/scenarios
uv run pytest tests/services/integrations tests/integrations
```

Full verification after all units:

```bash
cd ../..
make check
```

Optional but strongly recommended for the Pydantic AI jump, when credentials
are intentionally available:

```bash
EVALS_MODEL=<approved-model> make evals
```

## Completion criteria

- Every target is updated or explicitly rejected with evidence.
- The two Ruff findings are fixed without suppression.
- Each package-specific gate passes before the next update.
- `make check` passes.
- Agent behavior evals are run and pass, or their omission is explicitly
  recorded.
- Remote API, Docker, audit, and CodeQL checks pass.
