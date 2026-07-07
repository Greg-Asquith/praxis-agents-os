# Plan 042: Integrations UI — providers, connections, resources, context

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `docs/plans/000_README.md`.
>
> **Sibling-plan pre-flight (run before Step 1)**: this plan was written
> against the dictated 037–040 contract while those plans were in flight.
> Before coding, open the LANDED backend code and reconcile every route in
> the "Endpoint contract" table below against `apps/api/routes/integrations/`
> — exact paths, methods, request/response field names. The landed code
> wins; update the table (and this plan's affected steps) in the same
> commit. A *structural* mismatch (no manifest catalog endpoint, no
> connection status machine, context routes missing) is a STOP condition.
>
> **Drift check (run first)**: `git diff --stat a0eea1c..HEAD -- apps/web/src/app/router.tsx apps/web/src/config/navigation.ts apps/web/src/components/shell/ apps/web/src/features/conversations/components/conversation-detail-header.tsx apps/web/src/features/conversations/routes/conversation-route.tsx apps/web/src/features/schedules/ apps/web/src/features/tools/ apps/web/src/lib/api/`
> Changes from plan 040's Step 9 (schedule-form selector +
> `features/integrations/api/` seed files) are EXPECTED — build on them.
> Any other in-scope file changing means: compare the "Current state"
> excerpts against the live code before proceeding; on a mismatch, treat
> it as a STOP condition.

> **Amendment (2026-07-07, plan 061 — provider packaging)**: this plan
> additionally lands the frontend packaging seams from
> `docs/architecture/integration-packaging.md` §5 (the note wins on
> structure):
>
> 1. New `src/integrations/` namespace: `contract.ts` (the
>    `IntegrationUiModule` type + type-only re-exports of `ToolActivity`,
>    `ToolRowPresenter`/`ToolRowPresenterProps`, `ToolUi`) and
>    `registry.ts` (static `providerKey → () => import(...)` map — one
>    code-split chunk per provider, loaded only when the server catalog
>    reports the provider or its tools render in a conversation).
> 2. `renderCustomToolCallRow` and the tool-ui icon resolver consult
>    loaded integration modules after the core presenters; the
>    server-declared default row renders until a module resolves
>    (progressive enhancement — a provider chunk can never block chat).
> 3. New dependency-cruiser rules per note §5.5 (`src/integrations` may
>    import only `components/ui`, `lib`, and its own `contract`; features/
>    routes/app reach `src/integrations` only via `registry`/`contract`)
>    and knip entries for `src/integrations/*/index.ts`.
> 4. v1 ships **no** per-provider custom tool rows (note principle 2 —
>    041's presentations must suffice; that is the deliberate test of
>    default-first). Provider-specific connect help, if needed, ships as
>    an `IntegrationUiModule.ConnectHelp` component, not feature code.
> 5. The generic integrations feature (provider cards, connections,
>    resources, context picker) stays in `src/features/integrations/` as
>    planned — it is engine UI driven by the server catalog, not
>    provider-specific code.

## Status

- **Priority**: P1
- **Effort**: L
- **Risk**: MEDIUM (new product surface with credential-adjacent flows —
  the UI must never see or cache secret values; everything else is
  additive and server-enforced)
- **Depends on**: 038/039 (hard — connect flows, connection lifecycle,
  discovery, resource selection routes), 037 (hard, transitively — the
  manifest catalog the provider cards render). Soft: 040 (the context
  picker + groups editor sections need its routes; Steps 1–6 land without
  it), 041 (no code dependency — cards render any manifest entry; without
  041 the catalog is just empty in dev).
- **Category**: Phase 4a integrations (roadmap `000_MASTER_ROADMAP.md` §4
  row 042, decision D3; donor `DONOR_PORT_ROADMAP.md` §4.2 UI / §6 row C6;
  governance `governance.md` §1 role rows, §5 references-only)
- **Planned at**: commit `a0eea1c`, 2026-07-06

## Decisions taken

1. **Top-level `/integrations` route + nav item, not a workspace-settings
   tab.** The surface spans two ownership scopes (user-scoped Gmail
   connections AND workspace-scoped Google Ads/Airtable — D4) plus
   resource selection and context groups; burying that under the
   admin-flavored settings tabs (`workspace-settings-route.tsx:25-31`)
   would hide user-scoped connections from members. The nav item is NOT
   `managerOnly` (`config/navigation.ts:13-27` supports the flag) —
   governance §1 gives members connect/revoke rights on their own
   user-scoped integrations.
2. **Feature layout** per the AGENTS.md convention:
   `src/features/integrations/` with `api/` (one file per operation),
   `components/`, `routes/integrations-route.tsx`, `types.ts`, plus small
   pure helpers in `format.ts` (the `features/schedules/format.ts`
   precedent). Plan 040 Step 9 already seeded `types.ts` and two read
   api files (`get-active-context.ts`, `list-context-groups.ts`) — extend
   them, do not duplicate.
3. **The endpoint table below is an assumption to reconcile, not a
   contract to impose.** Written from the dictated 037–040 contract;
   pre-flight reconciles it against landed routes. Field-level
   differences are absorbed in `types.ts`; structural gaps STOP.
4. **Multi-connection UI (D3) is the default shape, not a mode**: every
   provider card shows ALL its connections as labeled rows with an
   always-visible "Add connection" action — no "already connected"
   dead-end state, no per-provider singleton assumption anywhere in the
   UI. Label rename is inline (pencil → input → save), revoke is a
   confirm dialog naming the label, `needs_reauth` renders a prominent
   "Re-authenticate" CTA that re-runs the OAuth initiate flow for that
   connection.
5. **API keys are write-only in the UI**: `<input type="password">`,
   value lives only in local component state, the connect mutation body
   is the only place it crosses the wire, the form resets on
   success/error, and no query or cache ever stores it. The backend
   returns references/metadata only (governance §5) — the UI renders
   "Key set · <provider> · <date>" style metadata, never a value, and
   there is no "reveal" affordance to build.
6. **OAuth connect flow**: a mutation POSTs initiate → response carries
   the provider authorize URL → `window.location.assign(url)` (full-page
   redirect; SPA state is rebuilt on return). The backend callback
   redirects to `/integrations?connection_id=...&status=...`; the route
   reads/validates those search params via TanStack Router search-param
   parsing, shows a success/error `Alert`, invalidates connection
   queries, and immediately `navigate({ replace: true })`s the params
   away so refresh doesn't replay the toast. Exact param names reconcile
   with 038's landed redirect (pre-flight).
7. **One status-rendering map for the 8-state machine** (037 contract:
   `auth_pending, discovery_pending, needs_resource_selection, active,
   degraded, error, revoked, needs_reauth`), in
   `components/connection-status-badge.tsx`: label + `Badge` variant +
   the single CTA each state earns (`needs_resource_selection` → "Select
   resources", `needs_reauth` → "Re-authenticate", `error` → "Retry
   test", `discovery_pending` → spinner + poll). Unknown status string →
   neutral badge with the raw value (fail visibly, don't crash — new
   backend states must not break stale clients).
8. **Discovery is polled, not streamed**: while any visible connection is
   `discovery_pending`, the connections query uses `refetchInterval:
   5000`. No new SSE events — the conversation stream parser throws on
   unknown event names (AGENTS.md), so REST polling is the
   compatibility-safe choice for v1.
9. **Resource selection is per-connection**: an expandable panel per
   connection listing discovered resources with enable checkboxes,
   grouped by `resource_type`, showing write-permission and lifecycle
   (`removed` rows disabled with a note). Google Ads renders its MCC
   hierarchy by indenting on the resource metadata `level`/parent fields
   (041 decision 6 metadata) — indentation only, no tree widget.
10. **Context groups editor** reuses the 027 provider-grouped picker
    *pattern* (`agent-tools-section.tsx` search + group-by-provider via
    `agent-tool-catalog-utils.ts`), not its components: a dialog with
    name field + searchable, provider-grouped, checkbox multi-select of
    enabled resources. Group rows show member counts and per-provider
    chips.
11. **The chat-header context picker writes the per-user-per-workspace
    selection — there is NO per-conversation override.** Verified against
    plan 040 decision 11 (its "Maintenance notes" bind 042 to this).
    The picker is a compact dropdown in `ConversationDetailHeader`
    (rendered at `conversation-route.tsx:156`): current selection name
    (or "No context"), groups then single resources, a "Clear" item, and
    a "Manage integrations" link to `/integrations`. Changing it mid-
    conversation affects the *next* run — the picker states that in a
    hint line, because resolution happens once per run (040 Step 7).
12. **One shared `ContextSelect` component** (`components/
    context-select.tsx`) backs both the chat-header picker and the
    schedule form, replacing 040 Step 9's minimal flat `Select` in
    `schedule-context-field.tsx`. Same options model, two triggers
    (header-compact and form-field).
13. **UI role-gating mirrors governance §1 but is convenience only** —
    the server enforces. Using `workspace.current_user_role`
    (`features/workspaces/types.ts:12`, checked as in
    `workspace-settings-form.tsx:46-47`): workspace-scoped connect/
    revoke and api-key entry render for owner/admin only; user-scoped
    connect/revoke for member+; resource selection and context groups
    member+; read_only gets a fully read-only page.
14. **Add shadcn `checkbox` and `switch` primitives** (needed by resource
    selection and the groups editor; `src/components/ui/` currently has
    neither — verified) via the shadcn CLI as vendored output, per the
    AGENTS.md "prefer adding shadcn components over hand-building" rule.
15. **No optimistic updates on credential-adjacent mutations** (connect,
    revoke, re-auth, resource enable): await the server, invalidate, and
    render returned state. Optimistically showing a connection as revoked
    or a resource as enabled when the server disagreed is a
    trust-surface bug, not a UX win. Label rename may seed the cache
    (`setQueryData`) since it is cosmetic.

## Why this matters

037–041 build a complete integrations engine with no face: connections
can only be created by hand-rolled requests, discovery outcomes are
invisible, and the active-context machinery that decides what agents
operate on has no picker. This plan is the "Surfaces" pillar for Phase 4a
(roadmap §1: nothing an agent can do is invisible): users see every
connection (multi-connection labels are D3's headline feature), select
the resources agents may touch, compose "Client X" context groups, and —
critically — always know which accounts the agent in front of them is
operating on, from the same header they read the conversation in. It is
also the last Phase 4a plan, closing the loop that lets 041's providers
be used by non-developers.

## Current state

All anchors verified at `a0eea1c`.

### Shell, routing, navigation

- `apps/web/src/app/router.tsx` — code-based route tree; the schedules
  block (lines 186-213) is the registration precedent: `createRoute` +
  `lazyRouteComponent(() => import("@/features/.../routes/..."), "...")`,
  parent `appRoute` (auth-gated in `beforeLoad`). Route list today:
  `/`, `/workspaces`, `/conversations[...]`, `/agents[...]`,
  `/skills[...]`, `/schedules[...]`, `/workspace-settings`, `/profile`,
  OAuth login/link callbacks (45-233). No `/integrations`.
- `apps/web/src/config/navigation.ts` — `mainNavigation` array (29-65)
  with `NavigationItem` supporting `managerOnly` (13-27);
  `navigationItemsForRole` (68-70) filters by
  `isWorkspaceManagerRole` (72). Nav today: Home, Agents, Skills,
  Schedules, Workspaces, Settings.
- `apps/web/src/components/shell/app-breadcrumbs.tsx` — path union at
  line 17 and label maps (~153) must learn `/integrations`.
- `apps/web/src/features/workspaces/routes/workspace-settings-route.tsx`
  — tabs Details/Members/Invitations/Audit (25-31); role check shape at
  13-14 (decision 1 rejects adding a tab here; cited so the executor
  doesn't "helpfully" move the surface).

### Data layer precedents

- `apps/web/src/lib/api/client.ts` — `apiRequest` builds URLs off
  `env.apiBaseUrl`, sends credentials, CSRF header on unsafe methods,
  and the workspace header via the registered headers provider. All
  feature requests go through it (AGENTS.md — no raw `fetch`).
- Query-key + read shape: `features/tools/api/list-tool-catalog.ts:9-17`
  (`toolsQueryKeys` with `activeWorkspaceQueryScope()` fallback
  `"__no_workspace__"`) and `features/schedules/api/list-schedules.ts:16-27`
  (nested `lists/list/detail/details` keys). Write shape:
  `features/schedules/api/create-schedule.ts:16-25` (`useMutation` +
  `invalidateQueries` on the list key).
- `features/tools/types.ts` + `ToolCatalogEntry` gain
  `provider_keys`/`resource_types` from 040 Step 5 — reconcile the type
  when landing (only the groups editor reads it, and only if useful for
  labeling; not load-bearing).

### Components to build on

- 027 picker precedent: `features/agents/components/agent-tools-section.tsx`
  (search input + provider filter + grouped list),
  `agent-tool-provider-group.tsx` (collapsible provider section with
  active counts), `agent-tool-catalog-utils.ts`
  (`groupToolsByProvider`/`filterTools`).
- Chat header: `features/conversations/components/
  conversation-detail-header.tsx:9-69` — title/badges/agent line, plus a
  metadata block; rendered once at
  `features/conversations/routes/conversation-route.tsx:156`. The picker
  slots into the right-hand column beside "Last activity".
- Schedule form: 040 Step 9 ships
  `features/schedules/components/schedule-context-field.tsx` (minimal
  flat `Select`) and `ScheduleFormState.activeContext` — Step 8 here
  swaps its internals for the shared `ContextSelect`.
- `src/components/ui/` primitives available: alert, avatar, badge,
  button, card, dialog, dropdown-menu, empty-state, field, icons, input,
  label, metric-card, pagination-controls, responsive-list, select,
  separator, skeleton, table, tabs, textarea. **No checkbox, no switch**
  (decision 14). `cn()` from `lib/utils.ts`; lucide icons; forms via
  native FormData helpers `lib/forms.ts` (`formString`/`formNumber`) —
  no form library (AGENTS.md).
- Role data: `features/workspaces/types.ts:12`
  (`current_user_role: WorkspaceRole | null`) via `useActiveWorkspace`.

### Endpoint contract (dictated — reconcile at pre-flight)

| Operation | Assumed route (under `/api/v1`) | Owner plan |
|---|---|---|
| Provider catalog (manifest-driven: key, label, auth mode, owner scope, resource types, availability, form help) | `GET /integrations/providers` | 037/038 |
| List connections (both scopes, with status/label/provider/owner) | `GET /integrations/connections` | 038 |
| OAuth initiate (new connection or re-auth) | `POST /integrations/connections/oauth/initiate` → `{authorize_url}` | 038 |
| API-key connect (label + secret value, write-only) | `POST /integrations/connections/api-key` | 038 |
| Test connection | `POST /integrations/connections/{id}/test` | 038 |
| Refresh credentials | `POST /integrations/connections/{id}/refresh` | 038 |
| Revoke connection | `POST /integrations/connections/{id}/revoke` (or DELETE) | 038 |
| Rename connection label | `PATCH /integrations/connections/{id}` | 038 |
| List discovered resources for a connection | `GET /integrations/connections/{id}/resources` | 039 |
| Enable/disable resources | `PUT /integrations/connections/{id}/resources` (id set or per-resource PATCH) | 039 |
| Retry discovery | `POST /integrations/connections/{id}/discovery` | 039 |
| Get active context (selection + resolved summary) | `GET /integrations/context` | 040 |
| Set / clear active context | `PUT /integrations/context` / `DELETE /integrations/context` | 040 |
| Context groups CRUD | `GET/POST /integrations/context-groups`, `PATCH/DELETE /integrations/context-groups/{id}` | 040 |

### Not relevant despite recent landings

Plans 013/030/031 landed between `0cbbb39` and `a0eea1c` (history
trimming, jobs harness, file models — `apps/api/models/files.py`,
`services/jobs/`). None have a frontend surface this plan touches; the
"Web - Jobs & Worker" commit (`c9e2bd3`) added **no** web feature
(verified — `src/features/` has no jobs directory). Discovery status
reaches this UI through 039's connection/discovery-run fields, not
through the jobs table.

## Commands you will need

| Purpose | Command (from `apps/web`) | Expected on success |
|---------|---------------------------|---------------------|
| Install | `pnpm install` | exit 0 |
| Full gate | `pnpm check` | exit 0, zero warnings (typecheck, eslint, prettier, knip, dep-cruiser, build) |
| Arch rules only | `pnpm arch` | no violations |
| Dev server | `pnpm dev` | app serves; `/integrations` renders |
| Add primitives | `pnpm dlx shadcn@latest add checkbox switch` | files in `src/components/ui/` |

## Scope

**In scope:**

- `src/features/integrations/types.ts` (extend 040's seed), `format.ts`
- `src/features/integrations/api/` (one file per operation):
  `list-providers.ts`, `list-connections.ts`, `initiate-oauth.ts`,
  `connect-api-key.ts`, `test-connection.ts`, `refresh-connection.ts`,
  `revoke-connection.ts`, `rename-connection.ts`, `list-resources.ts`,
  `update-resource-selection.ts`, `retry-discovery.ts`,
  `get-active-context.ts` + `list-context-groups.ts` (extend 040's),
  `set-active-context.ts`, `clear-active-context.ts`,
  `create-context-group.ts`, `update-context-group.ts`,
  `delete-context-group.ts`
- `src/features/integrations/components/`: `provider-card.tsx`,
  `provider-catalog.tsx`, `connection-row.tsx`, `connection-list.tsx`,
  `connection-status-badge.tsx`, `connect-oauth-button.tsx`,
  `api-key-connect-dialog.tsx`, `connection-label-editor.tsx`,
  `revoke-connection-dialog.tsx`, `resource-selection-panel.tsx`,
  `resource-row.tsx`, `context-groups-section.tsx`,
  `context-group-dialog.tsx`, `context-select.tsx`,
  `integrations-page-model.ts` (pure helpers if needed)
- `src/features/integrations/routes/integrations-route.tsx`
- `src/features/conversations/components/conversation-context-picker.tsx`
  + one-line mount in `conversation-detail-header.tsx`
- `src/features/schedules/components/schedule-context-field.tsx`
  (swap internals to `ContextSelect`)
- `src/app/router.tsx`, `src/config/navigation.ts`,
  `src/components/shell/app-breadcrumbs.tsx`
- `src/components/ui/checkbox.tsx`, `src/components/ui/switch.tsx`
  (vendored shadcn output)

**Out of scope (do NOT touch):**

- Any backend change. If a needed route is missing, that is a
  reconciliation finding (pre-flight/STOP), not a thing to add here.
- Per-conversation context overrides (decision 11 / 040 decision 11).
- SSE protocol changes (`features/conversations/stream/` untouched —
  decision 8).
- Secret display, download, or "reveal" affordances of any kind
  (decision 5); credential metadata beyond what the API returns.
- Provider-specific configuration screens (e.g. Ads report builders) —
  tools are the agent's, not the UI's.
- The agent-form tool catalog (027's surface) — integration tools appear
  there automatically via the registry API.
- Jobs UI, files UI, and anything from plans 032–036.

## Git workflow

- Branch: `advisor/042-integrations-ui`
- Commit style: `Web - Integrations UI` (split as `Web - Integrations
  Connections UI` / `Web - Active Context Picker` if landing in two
  slices — Steps 1–6 then 7–8)
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Types, query keys, read operations

Extend `features/integrations/types.ts` (040 seeded it) with hand-written
`type` aliases (no `interface` — lint-enforced): `IntegrationProvider`
(key, label, auth_mode, owner_scope, resource_types, available,
help/form metadata), `IntegrationConnection` (id, provider_key, label,
owner scope discriminants, status — a `ConnectionStatus` union of the 8
states, timestamps, last error metadata), `IntegrationResource` (id,
connection_id, resource_type, external_id, display_name, enabled,
write metadata, lifecycle, metadata record), `DiscoveryRun` summary,
plus the context types from 040 (`ActiveContextSelectionValue`,
`ContextGroup`, resolved summary).

Create `integrationsQueryKeys` in `api/list-connections.ts` (the
`schedulesQueryKeys` shape, `list-schedules.ts:16-27`): `all` →
workspace scope → `providers`, `connections`, `resources(connectionId)`,
`contextGroups`, `activeContext`. Read files export `queryOptions`
factories + `useSuspenseQuery` hooks: `list-providers.ts` (staleTime
60s — manifest data is near-static), `list-connections.ts` (accepts
`refetchInterval` passthrough for decision 8), `list-resources.ts`,
and extend 040's `get-active-context.ts` / `list-context-groups.ts` to
these keys if they used provisional ones.

**Verify**: `pnpm check` typecheck/eslint pass (unused-export knip
warnings are expected to disappear as later steps consume them — if
running the gate mid-plan, knip failures on not-yet-consumed exports are
acceptable ONLY between steps, never at the end).

### Step 2: Write operations

One `useMutation` file per operation (the `create-schedule.ts:16-25`
shape), each invalidating the narrowest correct keys:

- `initiate-oauth.ts` — body `{provider_key, connection_id?}`
  (connection_id present = re-auth); on success DO NOT invalidate —
  the very next statement is `window.location.assign(authorize_url)`.
- `connect-api-key.ts` — body `{provider_key, label, api_key}`;
  invalidates `connections`; the calling dialog owns clearing its local
  state regardless of outcome (decision 5).
- `test-connection.ts`, `refresh-connection.ts`, `revoke-connection.ts`,
  `retry-discovery.ts` — invalidate `connections` (+
  `resources(connectionId)` for retry-discovery).
- `rename-connection.ts` — `setQueryData` seed on the connections list
  then invalidate (decision 15 carve-out).
- `update-resource-selection.ts` — invalidates `resources(connectionId)`,
  `connections` (status may flip `needs_resource_selection` ↔ `active`),
  `activeContext`, and `contextGroups` (member availability changed).
- `set-active-context.ts` / `clear-active-context.ts` — invalidate
  `activeContext`.
- `create/update/delete-context-group.ts` — invalidate `contextGroups`
  + `activeContext` (a deleted group may be the current selection).

**Verify**: typecheck passes; each file exports exactly one hook (knip
clean once consumed).

### Step 3: Route shell, router, navigation, breadcrumbs

- `routes/integrations-route.tsx` — page shell: heading, role-aware
  subtitle, `Suspense` + skeleton fallbacks, then `ProviderCatalog`
  (Step 4) and `ContextGroupsSection` (Step 7). Validate the OAuth
  return search params (decision 6) with a hand-rolled parser (no
  schema library): read `connection_id`/`status`, render an `Alert`
  (success or the error detail), invalidate `connections`, and
  `router.navigate({ replace: true, search: {} })`.
- `src/app/router.tsx` — add `integrationsRoute` (`path:
  "/integrations"`, `lazyRouteComponent`, parent `appRoute`) following
  the schedules block (186-213); register in the route tree.
- `src/config/navigation.ts` — add `{label: "Integrations", to:
  "/integrations", icon: PlugIcon (lucide `Plug`), disabled: false}`
  between Schedules and Workspaces; NOT `managerOnly` (decision 1).
- `app-breadcrumbs.tsx` — extend the path union (line 17) and label
  entries (~153) for `/integrations`.

**Verify**: `pnpm dev` → nav shows Integrations; `/integrations` renders
the empty-state shell; breadcrumb reads Integrations; deep-link refresh
works (lazy route resolves).

### Step 4: Provider catalog + connection list

- `provider-catalog.tsx` — `useSuspenseQuery(listProviders)` +
  `useSuspenseQuery(listConnections)`; group connections by
  `provider_key`; render a `Card` per provider (`provider-card.tsx`):
  name, auth-mode/owner-scope badges ("Your account" vs "Workspace"),
  availability (an unavailable provider — 041 decision 9 env-gating —
  renders muted with "Not configured for this deployment"), the
  provider's `connection-list.tsx`, and the "Add connection" action
  (decision 4) — OAuth button or api-key dialog trigger by auth mode,
  role-gated per decision 13.
- `connection-row.tsx` — label (inline `connection-label-editor.tsx`:
  pencil → `Input` → save via rename mutation, Escape cancels),
  `connection-status-badge.tsx` (decision 7 map + its CTA), owner scope
  chip, created/last-refresh metadata line, and a `dropdown-menu` with
  Test / Refresh / Revoke (confirm via `revoke-connection-dialog.tsx`
  naming the label: "Revoke ‘Client X Ads’? Agents lose access to its
  resources."). Row expands to the Step 5 resource panel.
- Poll while pending: if any connection is `discovery_pending` or
  `auth_pending`, mount the connections query with `refetchInterval:
  5000` (decision 8), dropping the interval when none remain.

**Verify**: with two seeded connections on one provider (backend dev
data), both rows render with distinct labels and the add action remains
visible — the D3 acceptance check. Status badge renders every state
(temporarily point it at a fixture array in dev to eyeball all 8; remove
the fixture before committing).

### Step 5: Connect flows

- `connect-oauth-button.tsx` — button → `initiate-oauth` mutation →
  `window.location.assign(authorize_url)`; disabled+spinner while
  pending; error renders inline `Alert` (a failed initiate never leaves
  the page). The same component with `connectionId` set is the
  `needs_reauth` CTA (decision 4).
- `api-key-connect-dialog.tsx` — `Dialog` with native form + `FormData`
  helpers (`lib/forms.ts`): `label` (required, the D3 user-set label)
  and `api_key` (`type="password"`, `autoComplete="off"`, required),
  provider help text from the manifest entry (041 decision 5 documents
  Airtable PAT scopes there). Hand-rolled validation model (non-blank
  both). Submit → `connect-api-key` mutation → close + reset on
  success; on error keep the dialog, show the problem detail, and STILL
  clear the key field (decision 5). Admin-gated per decision 13.
- OAuth return handling was Step 3's search-param work; verify the
  round-trip against the local backend once 038's callback redirect is
  reconciled.

**Verify**: manual flow with the dev backend — api-key connect creates a
labeled connection and the key input is empty afterwards; devtools
network shows the key only in the single POST body; React Query devtools
show no cached key anywhere. OAuth initiate leaves the app and returns to
`/integrations` with a success alert that survives exactly one render
(params replaced).

### Step 6: Resource selection

- `resource-selection-panel.tsx` (mounted in the expanded connection
  row): `useSuspenseQuery(listResources(connectionId))`; group by
  `resource_type`; `resource-row.tsx` renders the shadcn `Checkbox`
  (decision 14) bound to `enabled`, display name, external id
  (muted mono), a "read-only" chip when write metadata is false, and
  Google Ads hierarchy indentation from resource metadata (decision 9;
  manager accounts render as non-checkable group headers when the
  backend marks them non-enableable). `removed` lifecycle rows are
  disabled with a "No longer available" note.
- Apply model: local pending set + explicit "Save selection" button
  calling `update-resource-selection` (decision 15 — no per-checkbox
  fire-and-forget), disabled while unchanged; a `needs_resource_selection`
  connection shows a callout above the panel ("Select at least one
  resource to activate this connection").
- Discovery controls: last discovery run status/time + "Re-run
  discovery" (`retry-discovery`), which flips the panel into the polling
  state (Step 4's interval picks it up).

**Verify**: enabling a resource on a `needs_resource_selection`
connection flips its badge to `active` after save (invalidations from
Step 2 doing their job); read-only and removed states render.

### Step 7: Context groups editor

- `context-groups-section.tsx` on the integrations page: table of groups
  (name, member count, per-provider chips via `format.ts`), New/Edit/
  Delete actions (member+, decision 13; delete confirms and warns "runs
  using this group will fall back to no context" — 040 decision 4
  semantics).
- `context-group-dialog.tsx` — name `Input` + the 027-pattern picker
  (decision 10): search input filtering enabled resources, provider
  sections with counts, `Checkbox` rows. Enabled resources come from the
  already-loaded connections/resources queries (fetch resources for all
  active connections here — acceptable at v1 scale; note the
  aggregation endpoint as a follow-up if it chafes). Submit →
  create/update mutation.

**Verify**: create "Client X" spanning a Gmail mailbox + an Ads account
+ an Airtable base (three providers, D3/donor's headline case); edit
replaces members; duplicate name surfaces the backend conflict as an
inline error.

### Step 8: Context picker (chat header + schedule form)

- `context-select.tsx` (decision 12) — options model: "No active
  context" / Groups (name + member count) / Resources (display name +
  provider label), built from `list-context-groups` +
  enabled-resources data, values encoded as `ActiveContextSelectionValue`.
  Two trigger variants: `compact` (header) and form-field.
- `conversation-context-picker.tsx` — mounts `ContextSelect compact`
  bound to `get-active-context` / `set-active-context` /
  `clear-active-context`; shows an amber dot when the resolved summary
  reports unavailable entries ("needs attention" title text); hint line
  "Applies to your next run in this workspace" (decision 11). Mount it
  in `conversation-detail-header.tsx` in the right-hand column above
  "Last activity" (`conversation-detail-header.tsx:60-65`); keep the
  header layout intact on mobile (it already stacks via
  `md:flex-row`).
- `schedule-context-field.tsx` — replace 040's flat `Select` internals
  with `ContextSelect` (form-field variant); the form state and payload
  wiring from 040 Step 9 stay as-is.
- Read-only members: the picker is fully functional for member+ (it is
  their own selection); `read_only` role renders it disabled with the
  current value visible (decision 13).

**Verify**: pick a group in the chat header → `PUT /integrations/context`
fires → reopening shows it selected; the schedule form renders the same
options; `pnpm arch` still clean (the conversations feature imports from
`features/integrations` — confirm dependency-cruiser allows
feature→feature imports as it does for schedules→agents today; if a rule
blocks it, move `context-select.tsx` consumption behind a re-export
inside conversations is NOT the fix — check how existing cross-feature
imports are structured and follow that pattern; restructure, never edit
the rules).

### Step 9: Final gate + manual QA sweep

Run the full static gate and the manual script below (no frontend test
framework exists — the gate is static + scripted QA, per AGENTS.md).

**Verify**: `pnpm check` exits 0 with zero warnings (knip: every api
file consumed; dep-cruiser: no violations; build succeeds).

## Test plan

Static gate: `pnpm check` (typecheck strict with
`exactOptionalPropertyTypes`, eslint zero-warnings, prettier, knip,
dependency-cruiser, build).

Manual QA script (run against the local stack, record results in the
completion report):

1. **Multi-connection (D3)**: two Airtable connections with distinct
   labels on one provider card; rename one inline; revoke it; the other
   survives untouched.
2. **OAuth round-trip**: Gmail connect → provider → back to
   `/integrations` with success alert; refresh does not replay the
   alert; connection proceeds `auth_pending → discovery_pending →
   needs_resource_selection` under polling without manual refresh.
3. **Secret hygiene**: api-key connect — key visible nowhere after
   submit (form, DOM, React Query cache, network responses).
4. **Resource selection**: enable/disable + save; badge flips;
   read-only chip on a `read`-permission Airtable base; Ads MCC
   hierarchy indents; manager row not enableable.
5. **Groups**: cross-provider group create/edit/delete; delete warning.
6. **Context picker**: header picker sets/clears selection; unavailable
   indicator appears after revoking a connection used by the selection;
   schedule form shows the same options; no per-conversation override
   exists anywhere.
7. **Roles**: as a `member` — no workspace-scoped connect/api-key
   controls, but own-user Gmail connect works and groups are editable;
   as `read_only` — page fully read-only.

## Done criteria

- [ ] `pnpm check` exits 0 with zero warnings
- [ ] `/integrations` registered, lazy-loaded, in nav (not managerOnly)
      and breadcrumbs
- [ ] Endpoint table reconciled against landed 038/039/040 routes, with
      the reconciliation noted in the completion report
- [ ] Multi-connection D3 flows work end to end (QA script item 1)
- [ ] API-key values are write-only (QA script item 3)
- [ ] All 8 connection statuses render distinctly with the correct CTA;
      unknown statuses render the neutral fallback
- [ ] Context picker present in the chat header and the schedule form,
      backed by one shared `ContextSelect`; 040's minimal schedule
      select is gone
- [ ] No per-conversation override surface exists (040 decision 11
      honored)
- [ ] `src/components/ui/checkbox.tsx` + `switch.tsx` added as vendored
      shadcn output only
- [ ] No `fetch` outside `lib/api`; no form/schema library added; no
      SSE changes
- [ ] Manual QA script results recorded in the completion report
- [ ] `git status` clean outside the in-scope list;
      `docs/plans/000_README.md` row updated

## STOP conditions

Stop and report back (do not improvise) if:

- 038 or 039 is not implemented, or the landed routes differ
  *structurally* from the endpoint table (no provider catalog endpoint,
  no connection status field/machine, no resource selection surface) —
  field-name drift you absorb in `types.ts`; missing capabilities you
  report.
- 040 is unimplemented when you reach Steps 7–8 — land Steps 1–6 as the
  first slice and report; do NOT stub context endpoints in the frontend.
- 038's OAuth callback does not redirect to a frontend URL you can
  handle with search params (e.g. it renders its own page) — the
  decision-6 flow needs rework, not a workaround.
- Any integration endpoint returns a secret value or full token — that
  is a backend defect (governance §5); report it, never render or cache
  it.
- The connection status values differ from the dictated 8-state machine
  — reconcile the decision-7 map first.
- `conversation-detail-header.tsx` or `conversation-route.tsx:156` no
  longer match the "Current state" shape (the header mount point moved).
- dependency-cruiser forbids the conversations→integrations import and
  no existing cross-feature pattern resolves it — restructuring that
  crosses plan scope needs an operator decision (do not edit
  `.dependency-cruiser.cjs`).
- You feel the need to add backend routes, a form library, optimistic
  credential updates, or per-conversation context state — scope leak.

## Maintenance notes

- **The status-badge map is the single place** new connection states get
  rendered; backend plans adding states must touch
  `connection-status-badge.tsx` in the same change (the neutral fallback
  keeps stale clients alive meanwhile).
- **Provider #4 costs zero UI work** by design: cards, connect flows,
  resource panels, and pickers are all manifest/data-driven. A provider
  needing bespoke UI (custom connect form fields beyond label+key,
  special resource pickers) should extend the manifest form metadata
  first — resist one-off components.
- **Polling → push**: if discovery latency makes 5s polling feel bad,
  the upgrade path is a new SSE event *shipped client-first* (the stream
  parser throws on unknown events — AGENTS.md ordering rule), not a
  faster interval.
- **Picker scale**: the flat groups+resources dropdown is fine to ~50
  entries; past that, add search inside `ContextSelect` (reuse the 027
  filter helpers) rather than a new widget.
- Reviewers should scrutinize: query invalidation breadth on
  `update-resource-selection` (four keys — missing one leaves stale
  status somewhere), the OAuth return param replace (no toast replay),
  the api-key dialog clearing the key on *error* paths too, and that
  role gating never *grants* anything the server would deny (it only
  hides).
