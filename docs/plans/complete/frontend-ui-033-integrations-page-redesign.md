# Plan 033: Integrations — calm app list, provider detail pages

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report — do not improvise.
> When done, update this plan's status row in
> `docs/plans/frontend-ui/README.md`.

## Status

- **Status**: DONE
- **Completed**: 2026-07-22
- **Written**: 2026-07-22 (anchors verified against the working tree at
  `27f9b18`, which carries in-flight roadmap plan 041b changes across the
  integrations feature — this plan builds on that working tree, not the
  bare commit)
- **Priority**: P1
- **Effort**: L
- **Risk**: MEDIUM — touches the OAuth return path and role-gated connect
  surfaces. All gating logic is preserved exactly; only where it renders
  changes. No backend changes.
- **Depends on**: nothing in this series (001–032 all landed). Coordinate
  with the in-flight roadmap plan 041b working tree — the live code wins
  on mechanics, this plan wins on visual direction.

## Goal

The Integrations page becomes something a non-technical operator can scan
in five seconds. Today it shows every layer of the system at once: a
2-column card grid where each provider card packs connection rows carrying
three badges each (status + "Your Account"/"Workspace" + "OAuth Sign
In"/"Service Account"), edit pencils, timestamps, kebab menus, expandable
resource trees, and one connect button per auth mode — then a "Context
Groups" card below with its own jargon. It is the last card-grid page in
the app (plan 011 de-carded everything else) and the only entity without
the list → detail shape Agents, Skills, and Schedules use.

After this plan:

1. **The index is a calm app list.** One row per provider: icon, name,
   one-line outcome description ("Let agents read and send your email"),
   a single derived summary chip ("Connected · 2 accounts", "Needs
   attention", "Not connected"), and a chevron. Nothing else. Context
   Groups stays below, copy-simplified.
2. **Each provider gets a detail page** at `/integrations/$providerKey`
   holding everything the card used to cram in: connected accounts,
   resource selection (the Google Ads manager-account hierarchy carries
   over unchanged — it is the best part of the current page), and one
   primary "Add Account" action.
3. **Auth mechanics disappear from default view.** No "OAuth Sign In" /
   "Service Account" badges, no owner-scope chips. Ownership becomes a
   plain sentence; sign-in method becomes muted meta text; the
   auth-mode choice moves inside the connect dialog with the advanced
   option de-emphasized.
4. **OAuth returns you to the work.** After signing in, the user lands on
   the provider detail page — where "choose what agents can use" is —
   not back at the top of the index.
5. **Copy states outcomes**: "Choose what agents can use", "Sign in
   again", "Disconnect" — not "needs_resource_selection", "Reauthenticate",
   "Revoke".

## Current state (verified 2026-07-22 at `27f9b18` + 041b working tree)

Frontend (`apps/web/src/features/integrations/`):

- `routes/integrations-route.tsx` (85 lines): `PageHeader`, OAuth
  status/error `Alert`s driven by `?integration_status` /
  `?integration_error` (cleared by a `useEffect` at lines 21–26 — a
  justified navigation-sync effect), then `ProviderCatalog` and
  `ContextGroupsSection` in `Suspense`.
- `components/provider-catalog.tsx`: fetches providers + connections,
  computes `canWrite` (non-read-only) and `canManageWorkspace`
  (owner/admin) at lines 18–19, lazy-loads integration UI modules, renders
  the `grid gap-4 xl:grid-cols-2` of `ProviderCard`s (line 37).
- `components/provider-card.tsx`: `Card` with display name,
  "{scope} connection" description, Available/Unavailable badge, embedded
  `ConnectionList`, and per-auth-mode connect buttons (lines 56–75) gated
  on `canConnect` (line 31: available && canWrite && (user-scope ||
  canManageWorkspace)).
- `components/connection-row.tsx` (243 lines): the overloaded row —
  chevron expander for discovery providers, `ConnectionLabelEditor`,
  `ConnectionStatusBadge`, owner-scope `Badge` (line 116), auth-mode
  `Badge` (lines 117–121), Added/Refreshed meta line, duplicate-account
  warning, inline error alert, contextual action button
  (Select Resources / Retry Test / Reconnect), kebab menu
  (Test / Refresh / Revoke), expandable `ResourceSelectionPanel`
  (lines 224–228), revoke `ConfirmDialog`.
- `components/connection-status.ts`: status → presentation map with
  labels "Connecting" / "Finding resources" / "Select resources" /
  "Active" / "Limited" / "Needs attention" / "Revoked" / "Reconnect" and
  follow-up actions.
- `components/resource-selection-panel.tsx`, `resource-selection-model.ts`,
  `resource-row.tsx`: resource fetching, hierarchy ordering
  (parent→child DFS), manager-account collapse, selection save,
  re-run discovery. **Keep all logic unchanged.**
- `components/context-groups-section.tsx`: context group list card with
  create/edit/delete via `ContextGroupDialog` + `ConfirmDialog`.
- `components/connect-oauth-button.tsx`: dual-mode — reconnect redirect
  button, or new-connection dialog; both send
  `next_path: "/integrations?integration_status=connected"` (lines 64,
  110). Multi-auth-mode providers get a "Sign in with Google" label
  (line 128).
- `components/service-account-connect-dialog.tsx`: Connection Name +
  Service Account JSON textarea. `api-key-connect-dialog.tsx`: name +
  key. Both validated by hand-rolled `*-form-model.ts`.
- `search.ts`: `validateIntegrationsSearch` sanitizes
  `integration_status` / `integration_error`.
- `format.ts`: `integrationOwnerScopeLabel` ("Your Account"/"Workspace"),
  `integrationAuthModeLabel` ("OAuth Sign In"/"API key"/title-cased).

Adjacent:

- `src/app/router.tsx`: `integrationsRoute` at lines 264–280 (loader
  prefetches providers, connections, context groups, resources); the
  OAuth callback route at lines 351–362. Detail-route precedent:
  `scheduleDetailRoute` at lines 300–317 (`$scheduleId` + `ensureQueryData`
  loader).
- `src/integrations/contract.ts`: `IntegrationUiModule` already carries
  optional `icons` (typed `LucideIcon` today) and `ConnectHelp` per
  provider — the extension point for per-provider presentation.
  `ToolUiIcon` (`features/conversations/components/tool-ui-icon.tsx:43`)
  already resolves tokens through `integrationIcon()` before the
  built-in lucide map, so provider modules can override tool icons with
  no renderer changes. Per the 2026-07-22 maintainer decision (series
  README), providers ship official brand logos as inline-SVG components.
- Backend `safe_next_path`
  (`apps/api/services/integrations/oauth/utils.py:88-92`) accepts any
  app-relative path — **the per-provider return path needs no backend
  change**.
- Role gating summary: read-only hides all connect/edit/delete;
  workspace-scoped providers additionally require owner/admin to
  connect/edit. Preserve exactly.
- Tests: `apps/web/tests/features/integrations/` (e.g.
  `resource-selection-model.test.ts`).

## Steps

### 1. Provider summary status — pure helper first

New `components/provider-status.ts`: `providerSummaryStatus(provider,
connections)` returning `{ label, variant, tone }` derived worst-first
from the provider's connections (revoked connections excluded from
counts):

- any `needs_reauth` or `error` → "Needs attention" (`destructive`)
- else any `auth_pending` / `discovery_pending` /
  `needs_resource_selection` → "Setting up…" (`warning`, pending)
- else any `active` / `degraded` → "Connected · N account" /
  "· N accounts" (`success`)
- else, provider unavailable (`configured_auth_modes` all false) →
  "Not available" (`secondary`)
- else → "Not connected" (quiet/no badge)

Unit-test the matrix in
`apps/web/tests/features/integrations/provider-status.test.ts` (tests
live under `tests/`, never colocated).

### 2. Index page: replace the card grid with a plain list

Rewrite `provider-catalog.tsx` as `provider-list.tsx` (delete
`provider-card.tsx`; `ConnectionList` moves to the detail page in step
3). Per plan 011, no wrapper card: divider-separated rows
(`divide-y`), whole row a TanStack `Link` to
`/integrations/$providerKey`:

- Left: the provider's brand logo in the standard `size-9`/`size-10`
  tile (white/neutral tile so official brand colors sit cleanly in both
  themes). The logo is an inline-SVG React component at
  `src/integrations/<provider_key>/logo.tsx`, registered on the
  provider's `IntegrationUiModule.icons` under the provider-key token
  (e.g. `icons.gmail`) and resolved via `integrationIcon()`. Widen
  `IntegrationUiModule.icons` in `src/integrations/contract.ts` from
  `Record<string, LucideIcon>` to
  `Record<string, ComponentType<SVGProps<SVGSVGElement>>>` (lucide
  icons remain assignable). Fallback while a module has no logo:
  `PlugZapIcon`. Provider tools adopt the same mark by declaring the
  provider-key icon token in their server-side `ToolUi` presentation —
  `ToolUiIcon` needs no changes beyond the widened type.
- Middle: `display_name` plus a one-line outcome description. Add
  optional `catalogDescription?: string` to `IntegrationUiModule`
  (`src/integrations/contract.ts`) — e.g. Gmail "Let agents read and
  send your email", Google Ads "Let agents report on your ad
  accounts" — fallback: "Connect {display_name} accounts for agents to
  use."
- Right: the step-1 summary chip + `ChevronRightIcon`. Unavailable
  providers render muted (no navigation-blocking — the detail page
  explains "Ask your administrator").
- Keep the existing `EmptyState` for zero providers
  (`provider-catalog.tsx:26-34`) and the module-loading effect
  (lines 22–24, external-system sync — justified).
- Update `ProviderCatalogSkeleton` in the route to match row shapes.

`ContextGroupsSection` moves to its own `/integrations/context-groups` page,
linked from a secondary action in the Integrations header. Its description
becomes outcome language ("Save a set of accounts agents use together, then
pick it when starting a conversation or schedule."). During implementation,
the maintainer directed the remaining card-in-card treatment to be removed:
the outer card, bordered inner list, icon tiles, and provider chips became a
plain section with divider rows and quiet provider text; behavior stayed
unchanged.

### 3. Detail route `/integrations/$providerKey`

Register `integrationProviderRoute` in `src/app/router.tsx` following
the `scheduleDetailRoute` pattern (lines 300–317): loader `ensureQueryData`
on providers + connections (resources load per-connection inside the
panel as today), `validateSearch: validateIntegrationsSearch` — the
OAuth status/error params move here (step 5). Lazy component
`routes/integration-provider-route.tsx`.

Page composition (plain sections, no wrapper cards):

1. **Header**: back-to-Integrations breadcrumb behavior per existing
   detail pages; `PageHeader` with provider display name, the
   `catalogDescription`, and — as the header action — the single
   primary **"Add Account"** button (step 4). Gate on the same
   `canConnect` predicate currently in `provider-card.tsx:30-32`.
   Unavailable provider: no action button, an info line "Not available
   for this deployment. Ask your administrator to set it up."
2. **OAuth callback alerts** (moved from the index route, same
   clearing effect pattern).
3. **Connected accounts**: the simplified `ConnectionRow` list
   (step 6), or a compact `EmptyState` ("No accounts connected yet.
   Add one to let agents use {name}.") whose action is the same Add
   Account flow.
4. If the provider has a `ConnectHelp` component
   (`contract.ts:32`), render it where the connect dialogs currently
   place it.

Unknown `$providerKey` → the standard not-found treatment other detail
routes use.

### 4. One "Add Account" entry; auth mechanics inside the dialog

New `components/add-account-button.tsx` replacing the per-auth-mode
button row (`provider-card.tsx:56-75`):

- Exactly one configured auth mode → the button opens that mode's
  existing dialog directly (`ConnectOAuthButton` dialog /
  `ApiKeyConnectDialog` / `ServiceAccountConnectDialog` — internals
  reused, only triggers change to render-prop/controlled `open`).
- Multiple modes (Google Ads today) → the button opens one dialog whose
  first step is a plain-language choice: primary option **"Sign in with
  Google"** ("Recommended — sign in and grant access in your browser")
  and, beneath a collapsed **Advanced** disclosure (native `<details>`,
  per the recorded collapsible decision), "Use a service account key"
  (and "Use an API key" where configured). Choosing one swaps the
  dialog body to the existing form for that mode.
- Service-account copy reframes the textarea as a credential-file
  paste: label "Service account key file", helper "Paste the contents
  of the key file you downloaded from Google." This is pasting a
  credential, not editing JSON — record in the plan-series README
  decisions if the maintainer confirms; the "users never see or edit
  JSON" decision (plan 022) bars JSON *editing surfaces*, and this
  stays behind Advanced.
- Button label: "Add Account" (Title Case, plan 013), `PlusIcon`
  `data-icon="inline-start"`.

### 5. OAuth lands on the detail page

In `connect-oauth-button.tsx`, both `next_path` literals (lines 64, 110)
become
`/integrations/${provider.provider_key}?integration_status=connected`.
Backend `safe_next_path` already allows any app-relative path — verify
by walking the flow, not by changing the API. OAuth error redirects that
carry `integration_error` back: confirm where the backend sends them
(the callback loader `routes/oauth-callback-loader.ts` builds the final
redirect) and point failures at the provider detail page too when the
provider key is known, else the index. Index route keeps accepting the
params (so old bookmarks don't break) but no longer needs to render the
alerts once nothing links there — keep its alert rendering only if the
error fallback still targets the index.

### 6. Declutter `ConnectionRow`

In `connection-row.tsx`, connections now render inside their provider's
page, so provider context is given. Remove from the default view:

- The owner-scope `Badge` (line 116) and auth-mode `Badge`
  (lines 117–121). Replace the meta line (lines 123–133) with plain
  words: `{ownership} · Added {date}` where ownership is
  "Only you can manage this" (user scope) / "Shared with the workspace"
  (workspace scope); append the sign-in method in plain words only when
  the provider has multiple configured auth modes ("Google sign-in" /
  "Service account key" / "API key"). Drop the separate
  api_key meta line (lines 129–133) — redundant with the above.
- Keep: `ConnectionLabelEditor`, one `ConnectionStatusBadge`, the
  contextual action button, the kebab, the duplicate-account warning,
  the inline error alert, the expandable `ResourceSelectionPanel`
  (all logic untouched).
- Copy in `connection-status.ts`:
  `auth_pending` "Connecting…" · `discovery_pending` "Finding your
  accounts…" · `needs_resource_selection` "Choose what agents can use"
  · `active` "Active" · `degraded` "Limited access" · `error`
  "Needs attention" · `revoked` "Disconnected" · `needs_reauth`
  "Sign in again". Contextual button labels follow: "Choose Resources"
  → keep verb-first Title Case ("Choose What Agents Use" is long — use
  "Choose Resources"), "Try Again" (was Retry Test), "Sign In Again"
  (reconnect).
- Kebab items: "Test Connection" → "Check Connection", "Refresh
  Credentials" → "Refresh Access", "Revoke" → "Disconnect" (confirm
  dialog: title "Disconnect this account?", body keeps the agents-lose-
  access consequence, confirm label "Disconnect"). API/mutation names
  unchanged.
- `format.ts`: update `integrationAuthModeLabel` to the plain words
  above; `integrationOwnerScopeLabel` callers shrink to the ownership
  sentence — remove the label helper if it ends up unused (knip will
  flag it).

### 7. Sweep and reconcile

- `resource-selection-panel.tsx`: copy-only pass ("Re-run Discovery" →
  "Look for New Resources", discovery status lines in outcome
  language). No logic changes; `resource-selection-model.ts` and its
  tests untouched.
- Grep for links/navigation to `/integrations` that should now deep-link
  to a provider (`MANAGE_INTEGRATIONS_SELECTION` in `active-context.ts`
  stays pointed at the index — correct, it is a general entry point).
- Update `apps/web/tests/features/integrations/` where labels or
  structure changed; add the step-1 unit tests.
- Both themes, keyboard focus on the new row links, `aria-label`s on
  icon-only buttons — per the series' shared rules.

## STOP conditions

- The in-flight 041b working tree has restructured any file this plan
  rewrites beyond what "Current state" describes → reconcile against
  live code first; if the shapes differ materially, stop and report.
- The OAuth callback flow rejects or strips the per-provider
  `next_path` in practice → stop; do not loosen backend path
  validation to force it through.
- Provider detail turns out to need data the existing queries don't
  carry (e.g. per-provider descriptions server-side) → stay with the
  frontend `IntegrationUiModule` extension in this plan; propose
  backend changes separately.
- The maintainer rejects the service-account "credential-file paste"
  framing under the no-JSON decision → stop and ask before shipping
  any service-account surface.

## Verification

- `cd apps/web && pnpm check` (typecheck, eslint zero-warnings, vitest,
  prettier, knip, depcruise, build) — the series gate.
- Visual QA against `pnpm dev` (API up via `make dev`), both themes,
  desktop + mobile widths:
  1. Index shows the plain provider list with correct summary chips for
     each seeded state; Context Groups below with new copy.
  2. Row click → provider detail; unknown key → not-found.
  3. "Add Account" on a multi-mode provider shows the choice step with
     Advanced collapsed; single-mode providers go straight to their
     dialog.
  4. Full OAuth round-trip lands on the provider detail page with the
     "Connection authorized" alert, then discovery → "Choose what
     agents can use" → resource selection (verify the Google Ads
     manager hierarchy still collapses/indents correctly) → save →
     status "Active"; index chip reads "Connected · 1 account".
  5. Disconnect flow: kebab → confirm dialog → row shows
     "Disconnected"; read-only role sees no connect/edit affordances;
     a member (non-admin) sees them only on user-scoped providers.
