# Plan 001: Enforce workspace-scoped Context Group resources and relevant-only fan-out

> **Executor instructions**: Read this plan fully before editing. Follow it
> step by step, run every verification command, and confirm the expected result
> before continuing. Preserve all unrelated worktree changes. Do not create a
> commit unless the human operator gives explicit approval. If a STOP condition
> occurs, stop and report it rather than improvising. When implementation is
> complete, update this plan's row in `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 49c00ed..HEAD -- apps/api/services/integrations/context apps/api/tests/services/integrations/context apps/api/tests/routes/integrations apps/web/src/features/integrations apps/web/tests/features/integrations apps/api/AGENTS.md apps/web/AGENTS.md docs/architecture/governance.md`
>
> This plan was authored while the main worktree already contained unrelated,
> uncommitted integration-page redesign changes, including changes to
> `context-group-dialog.tsx` and `context-groups-section.tsx`. Before editing,
> also run:
> `git diff -- apps/web/src/features/integrations/components/context-group-dialog.tsx apps/web/src/features/integrations/components/context-groups-section.tsx`.
> Preserve those changes and layer this plan's narrow behavior onto the live
> component structure. If the symbols or data flow described below no longer
> exist, treat that as a STOP condition.

## Status

- **Priority**: P0
- **Effort**: M
- **Risk**: MEDIUM-HIGH (workspace tenancy and external-tool targeting)
- **Depends on**: none
- **Category**: bug, security, tests
- **Planned at**: commit `49c00ed`, 2026-07-22

## Decisions this plan enforces

These decisions were made by the operator and are not open implementation
questions:

1. Context Groups inherit the scope of their current workspace. They do not
   gain a separate personal/shared scope field.
2. In a non-personal (shared) workspace, a Context Group may contain only
   resources whose connection is owned by that same workspace.
3. In a personal workspace, a Context Group may contain:
   - resources on connections owned by the current user; and
   - resources on connections owned by that personal workspace.
4. A personal workspace must never import resources owned by another
   workspace, even when the current user belongs to that workspace.
5. The workspace-only restriction applies to reusable Context Groups, not to
   direct single-resource active-context selection. A user may still select a
   personal connection as standalone context while acting in a shared
   workspace.
6. In a shared workspace's Context Group editor, personal resources are hidden,
   not rendered as disabled options. Helper copy explains that personal
   connections remain available as standalone context.
7. Tool relevance remains deterministic and server-owned: provider key plus
   resource type from `IntegrationToolBinding`. The model never selects a
   connection or resource id.
8. A tool fans out to every compatible resource and no incompatible resource.
   Example: Gmail search runs across every Gmail mailbox in the selected group
   but never against Google Ads resources.
9. The same logical resource discovered through multiple compatible
   connections executes once, using the existing preference order: active over
   degraded, then newest connection.
10. A write tool executes against compatible writable resources and returns a
    per-resource `write_not_permitted` error for read-only resources. One denied
    resource does not block the others.
11. There are no legacy or manually inserted shared-workspace groups containing
    personal resources. Do not add migration cleanup, legacy response states,
    or a new runtime unavailable reason for a case the operator has ruled out.

## Why this matters

Context Groups are meant to combine multiple provider and connection types,
while integration tools operate only on the compatible subset. The runtime
already implements relevant-only compatibility filtering, but group creation
and the UI currently disagree about connection ownership: the UI offers the
actor's personal Gmail resources in a shared workspace while the API accepts
only workspace-owned resources. This makes the intended Gmail + Google Ads
group fail at save time and leaves the central cross-provider promise without
an automated test.

The fix must enable mixed ownership only where it is safe: a personal workspace
can combine its owner's Gmail with resources owned by that personal workspace;
a shared workspace's reusable groups remain composed entirely of shared
workspace assets.

## Current state

### Workspace scope already exists

`apps/api/models/workspace.py:40-48` defines the durable scope discriminator:

```python
class Workspace(BaseModel):
    __tablename__ = "workspaces"
    # ...
    is_personal = Column(Boolean, default=False, nullable=False, server_default=text("false"))
```

No Context Group schema or migration is needed. Group scope must be derived from
this field.

### Connection visibility and group eligibility are currently different

`apps/api/services/integrations/connections/list_connections.py:28-30` lists
both the current workspace's connections and the current actor's personal
connections:

```python
visibility = (IntegrationConnection.owner_workspace_id == workspace.id) | (
    IntegrationConnection.owner_user_id == actor.id
)
```

That broad visibility is correct for the Integrations page and direct active
context. Do not narrow it globally.

`apps/api/services/integrations/context/utils.py:138-167` currently validates
Context Group members using only:

```python
IntegrationConnection.owner_workspace_id == workspace.id
```

`load_workspace_resources()` does not receive the actor. As a result, it always
rejects user-owned resources, including Gmail, even in a personal workspace.

`create_context_group.py:31-35` and `update_context_group.py:56-60` call that
helper with only `workspace` and `resource_ids`. Both operations already receive
the authenticated `actor`; thread it into the eligibility check.

### The UI offers resources that the shared-group API rejects

`apps/web/src/features/integrations/api/list-integration-resources.ts:11-32`
loads all visible connections and enriches each resource with provider,
connection label, and connection status. It currently drops the connection's
`owner_scope`, even though `IntegrationConnection` already exposes
`owner_scope: "user" | "workspace"` in
`apps/web/src/features/integrations/types.ts:49-64`.

`apps/web/src/features/integrations/components/context-group-dialog.tsx:57-65`
currently considers only enabled, available resources on active/degraded
connections. It does not consider workspace type or connection ownership.

`ContextGroupsSection` already has the active workspace via
`useActiveWorkspace()`, and `Workspace` exposes `is_personal`. Pass the boolean
to the dialog; do not add another workspace query or global state.

### Relevant-only runtime fan-out is already implemented

Do not redesign or duplicate this machinery:

- `services/integrations/context/domain.py:64-70` filters entries by
  `provider_keys` and `resource_types`.
- `services/agents/runtime/tools/registry.py:155-163` does not mount an
  integration-bound tool when the active context has no compatible entry.
- `services/integrations/context/fan_out.py:35-100` executes only
  `compatible_entries(binding)`, isolates failures, and applies the per-entry
  write gate.
- Gmail binds to `gmail` + `gmail_mailbox` in
  `integrations/gmail/tools/utils.py:26-34`.
- Google Ads binds to `google_ads` + `google_ads_account` in
  `integrations/google_ads/tools/utils.py:32-40`.
- `resolve_active_context.py:248-254` deduplicates on
  `(provider_key, external_id)` after ranking the connection.

The implementation work here is characterization coverage, not a new fan-out
algorithm.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Backend focused tests | `cd apps/api && TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/praxis_test uv run pytest tests/services/integrations/context tests/routes/integrations -q` | all selected tests pass |
| Backend lint | `cd apps/api && uv run ruff check services/integrations/context tests/services/integrations/context tests/routes/integrations` | exit 0 |
| Backend format check | `cd apps/api && uv run ruff format --check services/integrations/context tests/services/integrations/context tests/routes/integrations` | exit 0 |
| Frontend focused tests | `cd apps/web && pnpm vitest run tests/features/integrations/context-group-resource-model.test.ts` | all new tests pass |
| Frontend full gate | `cd apps/web && pnpm check` | exit 0, zero warnings |
| Database-backed API suite | `make api-test` | test database provisioned; all tests pass |
| Full repository gate | `make check` | exit 0 |

Run `make test-db` before the focused database command if the local test
database is not already available. `make api-test` provisions it automatically.

## Scope

### In scope

- `apps/api/services/integrations/context/utils.py`
- `apps/api/services/integrations/context/create_context_group.py`
- `apps/api/services/integrations/context/update_context_group.py`
- `apps/api/tests/services/integrations/context/test_context_groups.py`
- `apps/api/tests/services/integrations/context/test_fan_out.py`
- `apps/api/tests/routes/integrations/test_context_routes.py`
- `apps/web/src/features/integrations/types.ts`
- `apps/web/src/features/integrations/api/list-integration-resources.ts`
- `apps/web/src/features/integrations/components/context-group-dialog.tsx`
- `apps/web/src/features/integrations/components/context-groups-section.tsx`
- `apps/web/src/features/integrations/components/context-group-resource-model.ts` (new)
- `apps/web/tests/features/integrations/context-group-resource-model.test.ts` (new)
- `apps/api/AGENTS.md`
- `apps/web/AGENTS.md`
- `docs/architecture/governance.md`
- `plans/README.md` (status only when implementation completes)

### Out of scope

- Database migrations or changes to `IntegrationContextGroup`.
- A separate scope/owner field on Context Groups.
- Changing provider manifests or changing Gmail from user-owned to
  workspace-owned.
- Narrowing connection-list or connection-resource endpoints; personal
  connections must remain visible for management and direct context selection.
- Changing `load_selection_resource()` or forbidding standalone personal
  resource context in a shared workspace.
- Runtime handling for impossible legacy/corrupt shared groups containing
  personal resources.
- New runtime compatibility semantics, model-selected connection ids, or tool
  schema parameters for accounts/connections.
- Fan-out concurrency.
- Changing duplicate-resource ranking or partial write behavior.
- Refactoring the existing integration-page redesign.

## Git workflow

- Work in the existing worktree unless the operator asks for a branch.
- Preserve unrelated modified and untracked files shown by `git status`.
- Do not stage, commit, push, or open a pull request without explicit human
  authorization.
- Keep implementation changes focused; do not format unrelated files.

## Steps

### Step 1: Centralize the Context Group resource-eligibility predicate

In `apps/api/services/integrations/context/utils.py`, make
`load_workspace_resources()` receive `actor: User` and construct exactly this
ownership rule:

```python
ownership = IntegrationConnection.owner_workspace_id == workspace.id
if workspace.is_personal:
    ownership = or_(ownership, IntegrationConnection.owner_user_id == actor.id)
```

Apply `ownership` alongside the existing resource-id, soft-delete, and
connection soft-delete filters. Do not admit a connection owned by another
workspace. Do not change `load_selection_resource()`, whose broader visibility
is deliberately retained for standalone context.

Update `create_context_group()` and `update_context_group()` to pass their
existing `actor` into `load_workspace_resources()`.

Keep the current all-or-nothing validation: if any submitted id is ineligible,
raise `AppValidationError` with `field="resource_ids"`; do not silently omit it.
Use product-facing wording that says resources must be available to Context
Groups in the current workspace, without exposing whether an inaccessible id
exists elsewhere.

**Verify**:

```bash
cd apps/api
uv run ruff check services/integrations/context
uv run ruff format --check services/integrations/context
```

Expected: both commands exit 0.

### Step 2: Pin backend ownership and mixed-provider group behavior

Extend
`apps/api/tests/services/integrations/context/test_context_groups.py`, following
its existing factory-based database setup. Add distinct resources and
connections so the tests prove ownership rather than accidentally reusing the
same connection:

1. **Shared workspace rejects actor-owned resource**: create a user-owned Gmail
   connection/resource for the actor and assert group creation raises
   `AppValidationError` when the current workspace has `is_personal=False`.
2. **Shared workspace accepts mixed workspace-owned providers**: create two
   connections owned by the shared workspace with different provider keys and
   resource types (Gmail-like test data is acceptable even though the real
   Gmail manifest is user-owned; service validation is ownership-based, while
   the test's provider keys establish cross-provider storage). Assert one group
   returns both member ids.
3. **Personal workspace accepts actor-owned plus current-workspace-owned**:
   set up a personal workspace, an actor-owned Gmail resource, and a Google Ads
   resource owned by that personal workspace. Assert one group stores both.
4. **Personal workspace rejects another workspace's resource**: even when the
   actor is also a member/owner there, assert the resource cannot be included.
5. Exercise update as well as create: adding an ineligible personal resource to
   an existing shared group fails atomically and leaves the prior member set
   unchanged.

Add one route-level regression in
`apps/api/tests/routes/integrations/test_context_routes.py` proving the API
returns the standard validation problem response for a shared workspace's
user-owned resource. Do not duplicate every service test at the route layer.

Do not add a migration or a legacy malformed-row test.

**Verify**:

```bash
make test-db
cd apps/api
TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/praxis_test \
  uv run pytest tests/services/integrations/context/test_context_groups.py \
  tests/routes/integrations/test_context_routes.py -q
```

Expected: all selected tests pass, including at least five new service cases
and one new route assertion.

### Step 3: Preserve and explicitly characterize relevant-only fan-out

Extend `apps/api/tests/services/integrations/context/test_fan_out.py`. Generalize
its private entry fixture helper only as much as needed to accept a provider key
and resource type. Add one mixed-context test containing:

- two compatible Gmail mailbox entries on different connections;
- one incompatible Google Ads account entry; and
- a Gmail binding.

Have the operation record each received resource. Assert it is called exactly
for the two Gmail entries, the Ads entry is absent from both calls and results,
and result ordering follows the compatible-entry ordering.

Keep the existing write-gate test and partial-failure test unchanged. The
existing resolution suite already pins duplicate-resource selection; do not
reimplement deduplication in fan-out.

This step should require tests only. If the new test fails against the current
`compatible_entries()` implementation, STOP and report the unexpected runtime
drift before modifying production fan-out code.

**Verify**:

```bash
cd apps/api
uv run pytest tests/services/integrations/context/test_fan_out.py \
  tests/services/integrations/context/test_context_binding.py -q
```

Expected: all tests pass; the mixed-context test proves the Ads entry was never
passed to the Gmail operation.

### Step 4: Carry connection ownership into the frontend resource model

In `apps/web/src/features/integrations/types.ts`, add a required enriched field
to `IntegrationResource` named `connection_owner_scope` with the existing
`IntegrationOwnerScope` type. Because resources returned directly by the API do
not include this client-enrichment field, update the local `ResourceResponse`
type in `list-integration-resources.ts` to omit it alongside
`connection_label` and `provider_key`.

In `list-integration-resources.ts`, set:

```ts
connection_owner_scope: connection.owner_scope
```

when flattening each connection's resources. Do not change the backend resource
response contract and do not add another API call.

Search all `IntegrationResource` fixtures in frontend tests and supply the new
required field where needed. Do not make the enriched field optional merely to
avoid updating fixtures; group eligibility must fail at compile time if future
callers forget ownership.

**Verify**:

```bash
cd apps/web
pnpm typecheck
```

Expected: exit 0 with no missing `connection_owner_scope` errors.

### Step 5: Make Context Group picker eligibility pure and workspace-aware

Create
`apps/web/src/features/integrations/components/context-group-resource-model.ts`
with one small, pure exported function. It should accept the resources and
`isPersonalWorkspace`, and return resources eligible for the group editor:

- always require `enabled === true`;
- always require `availability === "available"`;
- always require connection status `active` or `degraded`;
- in a personal workspace, allow `connection_owner_scope` of `user` or
  `workspace` (the resource list has already enforced actor/current-workspace
  visibility);
- in a shared workspace, allow only `connection_owner_scope === "workspace"`.

Use this helper from `context-group-dialog.tsx` instead of its inline eligibility
filter. Add an `isPersonalWorkspace: boolean` prop, supplied from
`ContextGroupsSection` using its existing active `workspace.is_personal` value.

In a shared workspace, render concise helper copy beneath the Resources label:
personal connections are not shown in shared groups but remain selectable as
standalone context in conversations and schedules. Do not show disabled
personal rows and do not mention internal ownership ids.

Preserve the current search, provider grouping, selected-count copy, provider
marks, and the uncommitted integration-page redesign. Do not redesign the
dialog.

Create
`apps/web/tests/features/integrations/context-group-resource-model.test.ts`
covering:

1. shared workspace includes eligible workspace-owned resources;
2. shared workspace excludes otherwise-eligible user-owned resources;
3. personal workspace includes both current-user and current-workspace assets;
4. both workspace types still exclude disabled, unavailable, removed, and
   inactive-connection resources.

**Verify**:

```bash
cd apps/web
pnpm vitest run tests/features/integrations/context-group-resource-model.test.ts
pnpm typecheck
pnpm eslint . --max-warnings 0
```

Expected: all new tests pass; typecheck and ESLint exit 0.

### Step 6: Document the invariant at its maintenance boundaries

Update documentation without referencing this plan number from runtime code:

- `apps/api/AGENTS.md`: under Agent Runtime and Providers, state that Context
  Group member eligibility derives from `Workspace.is_personal`: shared
  workspace groups accept only same-workspace connections; personal workspace
  groups additionally accept the actor's user-owned connections. Standalone
  resource selection deliberately keeps actor-or-workspace visibility.
- `apps/web/AGENTS.md`: under Data and API or UI, state that the shared-workspace
  Context Group picker hides personal resources while standalone context
  selection may show them.
- `docs/architecture/governance.md`: record the durable scope rule beside the
  integration-resource/context-group governance row. Keep the text behavioral;
  do not cite this advisor plan.

**Verify**:

```bash
rg -n "Context Group|context group|is_personal|personal connections" \
  apps/api/AGENTS.md apps/web/AGENTS.md docs/architecture/governance.md
```

Expected: all three documents contain the invariant, and none imply that
personal connections can be shared through a shared workspace group.

### Step 7: Run focused and full gates, then review scope

Run:

```bash
make api-test
cd apps/web && pnpm check
cd ../.. && make check
git status --short
git diff --check
```

Expected:

- all backend tests pass against the provisioned Postgres test database;
- all frontend checks pass with zero warnings;
- the full repository gate exits 0;
- `git diff --check` reports no whitespace errors;
- `git status --short` shows only pre-existing user changes plus files listed in
  this plan's scope.

Review the final diff specifically for accidental changes to direct active
context selection, connection visibility, provider bindings, or the ongoing
integration-page redesign.

## Test plan summary

Backend database tests:

- shared group accepts multiple workspace-owned providers;
- shared group rejects an actor-owned resource;
- personal group accepts actor-owned plus personal-workspace-owned resources;
- personal group rejects another workspace's resource;
- failed update is atomic;
- route returns structured validation failure.

Backend pure runtime characterization:

- mixed active context fans a Gmail binding only to Gmail mailboxes;
- existing partial-failure, duplicate-resolution, and write-denial tests remain
  green.

Frontend pure tests:

- eligibility changes with `workspace.is_personal`;
- connection lifecycle/resource availability filters remain enforced;
- the shared picker never receives personal rows to render.

No live provider calls are required. Do not add Gmail/Google Ads credentials to
tests.

## Done criteria

- [ ] Shared-workspace Context Groups accept only resources whose connection has
      `owner_workspace_id == current workspace.id`.
- [ ] Personal-workspace Context Groups accept same-workspace connections plus
      connections with `owner_user_id == actor.id`.
- [ ] Resources owned by another workspace are rejected in every workspace
      type.
- [ ] Direct single-resource active context retains current actor-or-workspace
      visibility.
- [ ] Shared-workspace group UI hides user-owned resources and explains that
      standalone context remains available.
- [ ] A mixed-provider fan-out test proves operations receive only compatible
      provider/resource entries.
- [ ] Existing deduplication and partial write-gating tests remain green.
- [ ] No database migration or Context Group scope column is added.
- [ ] `make api-test` exits 0.
- [ ] `cd apps/web && pnpm check` exits 0.
- [ ] `make check` exits 0.
- [ ] `git diff --check` exits 0.
- [ ] No unrelated worktree changes are overwritten, staged, or committed.
- [ ] `plans/README.md` marks Plan 001 DONE only after all checks pass.

## STOP conditions

Stop and report back if any of these occurs:

- `Workspace.is_personal` is removed or no longer means personal versus shared
  workspace.
- Connection ownership no longer obeys the `owner_user_id` XOR
  `owner_workspace_id` invariant.
- Context Group CRUD no longer receives both the active workspace and actor.
- The live Context Group UI no longer gets resources through
  `list-integration-resources.ts` or no longer has access to the active
  workspace.
- Supporting the rule appears to require a database migration or Context Group
  scope column.
- The mixed-context fan-out characterization test fails against the current
  compatibility code.
- The implementation would require changing direct resource selection,
  provider bindings, or connection-list visibility.
- Existing uncommitted frontend changes cannot be preserved cleanly.
- A verification command fails twice after one focused correction.

## Maintenance notes

- The Context Group eligibility predicate is a tenancy boundary. Future group
  import, bulk-edit, or API paths must call the same backend helper rather than
  reimplementing owner checks.
- Frontend filtering is UX only; backend validation remains authoritative.
- If a provider later supports both user-owned and workspace-owned connections,
  eligibility still follows the concrete connection owner, not the provider
  manifest's default scope.
- If shared conversations or shared schedules are introduced later, revisit
  standalone personal active context separately. That future feature must not
  silently broaden Context Group membership.
- Reviewers should scrutinize the personal-workspace OR predicate: it must be
  `(same personal workspace) OR (current actor)`, never arbitrary workspace
  membership.
- Relevant-only fan-out stays defined by the tool binding. Any future need for
  semantic targeting within a provider (for example, message provenance to one
  mailbox) requires a separate explicit design; do not smuggle model-selected
  connection parameters into tool schemas.
