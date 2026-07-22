# Plan 082: Capability catalogue prerequisites — tool versioning, input schemas, workspace tool grants, and the authenticated schema surface

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `docs/plans/000_README.md`.
>
> **Design-note pre-flight**: this plan implements the "cheap contract
> prerequisites" of `docs/architecture/internal-applications.md` §10 (adopted
> 2026-07-20, decision D13). Re-read §8 (substrate table) before coding; the
> note wins on intent. This plan deliberately lands *before* Phase 7 code so
> the catalogue does not harden around the missing fields — 041 multiplies
> the catalog with provider tools, and retrofitting `version`/schemas after
> that is a migration instead of a default.
>
> **Drift check (run first)**:
> `git diff --stat 1bc7c03..HEAD -- apps/api/services/agents/runtime/tools/ apps/api/routes/tools/ apps/api/main.py apps/api/models/`
> Compare the "Current state" excerpts against live code before proceeding.

## Status

- **Priority**: P1
- **Effort**: S-M
- **Risk**: LOW-MED (additive contract fields and a default-allow grant seam;
  the only behavior-bearing change is the grant store, which ships with
  default-allow semantics identical to today's stub)
- **Depends on**: 025/026 (DONE). Plan 041 completed with the first 10
  provider tools before this prerequisite landed; execute this as the immediate
  catalogue-hardening follow-up, before 083 or any further provider expansion.
- **Category**: Phase 7 prerequisite (roadmap §4 Phase 7; design note
  `internal-applications.md` §10)
- **Planned at**: commit `1bc7c03`, 2026-07-20

## Decisions taken

1. **`version` on the tool contract.** `RuntimeToolDefinition` gains
   `version: int = 1`, import-time validated ≥ 1. Bump on breaking changes
   to argument or output shape; additive changes do not bump. The catalog
   route exposes it; dispatch records it in the tool audit metadata so
   audit rows are interpretable after a tool evolves. Application contracts
   (085) later pin `name@version` expectations against this field.
2. **Serialized input schemas on the catalog.** Each catalog entry carries
   `input_schema`: the JSON Schema pydantic-ai derives for the tool's
   arguments, serialized once at registration (function-kind tools).
   Capability-kind and native entries without a Python signature expose
   `input_schema: null`. This is the machine-readable half of the
   building-block catalogue the app kit (087) snapshots for coding agents.
3. **Real `is_tool_allowed`: default-allow with explicit workspace
   disables** [default — confirm at review]. A `workspace_tool_settings`
   core table (workspace_id, tool_name, enabled, updated_by, timestamps;
   unique on workspace+tool) backs the seam. Absence of a row means
   allowed — zero rows reproduces today's `return True` exactly. Owner/
   admin routes toggle a tool off/on per workspace; changes are audited
   (`resource_type="tool"`). The seam signature already accepts
   `workspace`/`agent`; it becomes a real lookup (cached per request
   scope, not per call). No per-agent grants in v1 — agents are already
   scoped by `Agent.tool_names`.
4. **Authenticated schema surface, not anonymous docs.**
   `GET /api/v1/meta/openapi.json` returns `app.openapi()` behind normal
   session auth (any authenticated user; the schema describes routes, not
   data). `docs_url`/`redoc_url`/`openapi_url` stay `None` — the 078
   posture (anonymous spec serving rejected) is narrowed, not reversed;
   078 carries a coordinating amendment. The app kit's typed-client
   generation (087) consumes this route with a dev token.
5. **No UI in this plan.** The workspace tool-disable surface is
   backend-only until the integrations settings UI (042) or a later polish
   pass gives it a natural home; per AGENTS.md the pending UI is
   documented, not implied.

## Why this matters

Three of the four items are one-liners today and migrations later: the
catalog is about to grow provider tools (041), external consumers (apps,
085+) will pin against it, and a catalogue without input schemas or
versions cannot be a contract. The grant seam is the security-relevant
one — `is_tool_allowed` is a documented seam that currently returns `True`
unconditionally, which is fine while every tool is first-party but wrong
the moment workspace operators need to switch off a spend-capable tool
without editing every agent.

## Current state

Verified at `1bc7c03` (2026-07-20).

- `services/agents/runtime/tools/contract.py:96-124` —
  `RuntimeToolDefinition` has no `version` field and no serialized input
  schema; `to_pydantic_tool` builds the pydantic-ai `Tool` whose args
  schema exists only transiently inside pydantic-ai.
- `services/agents/runtime/tools/permissions.py:8-15` — `is_tool_allowed`
  is a hardcoded `return True` with the final-form signature.
- `services/agents/runtime/tools/registry.py:146,181,219` — the three call
  sites (turn assembly ×2, catalog filtering) already pass
  `workspace`/`agent`.
- `routes/tools/list_catalog.py` — the catalog route serializes contract
  metadata; no schema/version fields.
- `apps/api/main.py:77` — `openapi_url=None` (with docs/redoc); 078
  decision 2 exports the schema as a CI artifact only.
- Tool audit rows carry `tool_name`/`tool_provider` (026); metadata is the
  extension point for `tool_version`.

## Scope

**In scope:**

- `services/agents/runtime/tools/contract.py` (add `version`, schema
  serialization helper), `registry.py` (expose serialized schemas),
  `permissions.py` (real lookup)
- `models/workspace_tool_settings.py` (create) + `models/__init__.py` +
  core migration
- `services/tools/` or the existing tool-catalog service seam: grant
  read/write operations (one per file), audit writes
- `routes/tools/` — catalog response gains `version`/`input_schema`;
  new admin toggle routes
- `routes/meta/` (create) — authenticated `openapi.json` route +
  `main.py` router include
- Tests: contract invariants, grant semantics (absence=allow, disable
  hides from catalog and turn assembly, audit row on toggle), schema
  route auth

**Out of scope (do NOT touch):**

- Any frontend change; app-principal enforcement (083/084); per-agent or
  per-role grant models; anonymous docs routes; the CI OpenAPI export
  (078 owns it).

## Git workflow

- Branch: per operator direction (standing 2026-07-20 preference: work on
  `main`)
- Commit style: `API - Capability Catalogue Prerequisites`
- Do NOT commit without explicit operator approval.

## Steps

### Step 1: Contract fields

Add `version: int = 1` to `RuntimeToolDefinition` with an import-time
invariant (`version >= 1`) beside the existing contract checks. Add a
`serialized_input_schema()` helper that builds the pydantic-ai `Tool` once
at registration for function-kind entries and captures its JSON schema;
store on the definition (cached), `None` for non-function kinds.

**Verify**: registry import passes; a REPL check shows a function tool's
schema contains its parameter names; ruff exit 0.

### Step 2: Grant store + seam

Create the `workspace_tool_settings` model + core migration (D5). Service
operations: `get_disabled_tools(db, workspace)` (set of names, request-
scoped cache), `set_tool_enabled(db, *, workspace, tool_name, enabled,
actor)` (validates the tool exists in the registry, upserts, audits).
Rewrite `is_tool_allowed` to consult the disabled set when a workspace is
provided; `workspace=None` (internal contexts) stays allow-all. Thread the
disabled set through the three registry call sites without per-tool
queries.

**Verify**: with zero rows, catalog and turn assembly are byte-identical
to before (test pins this); disabling a tool removes it from the catalog
and from turn assembly; audit row written.

### Step 3: Catalog + admin routes

Catalog entries gain `version` and `input_schema`. New routes (owner/admin,
one per file): `PUT /api/v1/tools/{tool_name}/availability` body
`{enabled: bool}`; unknown tool → 404. Response schemas in the tools
service schemas module.

### Step 4: Authenticated schema route

`routes/meta/get_openapi_schema.py`: `GET /api/v1/meta/openapi.json`,
normal auth dependency (no workspace requirement), returns `app.openapi()`
with `Cache-Control: no-store`. Include the router in `main.py`;
`openapi_url` stays `None`.

**Verify**: unauthenticated → 401; authenticated → valid JSON schema
containing known route paths.

### Step 5: Tests + audit metadata

Dispatch audit metadata records `tool_version`. Test files pin: contract
invariants (version ≥ 1, schema presence by kind), grant semantics,
route auth matrix, schema route.

## Test plan

~12–16 tests across contract, permissions, routes. Pinned invariants:
**zero grant rows changes nothing**, **a disabled tool disappears from
both catalog and turn assembly**, **toggles are audited**, **the schema
route requires auth**, **every function tool serializes a schema**.

## Done criteria

- [ ] `uv run ruff check .` exit 0; `uv run alembic check` clean;
      migration downgrade round-trips
- [ ] Catalog entries expose `version` and `input_schema`
- [ ] `is_tool_allowed` performs a real lookup; default-allow pinned by test
- [ ] Authenticated schema route live; anonymous docs still disabled
- [ ] `TEST_DATABASE_URL=... uv run pytest tests/services/agents/runtime tests/routes/tools -q` passes
- [ ] `docs/plans/000_README.md` status row updated

## STOP conditions

- A pending plan has claimed `is_tool_allowed` or added tool-grant tables
  since this plan was written (re-check 040–042 amendment blocks).
- The catalog route shape has been consumed by a frontend change that a
  new field would break (should be additive; verify).
- Serializing input schemas requires executing tool functions or pulls in
  request-time cost — schemas must be computed once at import/registration.
- You feel the need to build per-agent or per-role grants — scope creep;
  record as a follow-up instead.

## Maintenance notes

- 083 consumes `version` + grants (app envelopes must respect workspace
  disables); 085 pins contract `name@version`; 087 snapshots
  `input_schema` into the builder catalogue. Keep all three fields stable.
- When a tool's arguments change breaking-ly, the review checklist is:
  bump `version`, check app contracts that pin the old version (085's
  validation reports them), note in the tool's docstring.
- The workspace disable surface deserves UI eventually — natural home is
  workspace settings; record in the polish lane when picked up.
