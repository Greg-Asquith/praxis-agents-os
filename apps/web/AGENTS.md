# Frontend Standards (apps/web)

Vite, React 19, TypeScript (strict, with `exactOptionalPropertyTypes` and
friends), Tailwind CSS 4, managed with `pnpm`. A single-page app with no
server runtime. Repo-wide expectations are in the root `AGENTS.md`.

## Structure

- `src/app/` is bootstrap only (App, router, query client); `src/config/` is
  plain data and env parsing; `src/lib/` holds framework-light helpers
  including the API client; `src/components/ui/` holds shadcn primitives,
  with shared form and shell composition in `src/components/forms/` and
  `src/components/shell/`; `src/routes/` holds top-level route shells.
- Feature code lives in `src/features/<feature>/` with `api/`, `components/`,
  `routes/`, and a feature-local `types.ts`. Follow this layout for new
  features.
- Integration provider UI lives in `src/integrations/<provider>/` with
  `index.ts` (the `IntegrationUiModule` default export — the only file the
  registry imports), `presenters/` (tool row presenters), `components/`
  (provider-specific visual components, including the logo), `lib/`
  (non-visual helpers such as arg parsing and detail builders), and `api/`
  (TanStack Query operations, one per file) when the provider calls the API.
  Follow this layout for new providers.
- Layering is enforced by `.dependency-cruiser.cjs` (`pnpm arch`): no cycles;
  `components/ui` stays generic; `lib/api` stays framework-light; features do
  not import route shells; routes do not import `app/`. Fix violations by
  restructuring, not by editing the rules.
- Routing is TanStack Router with a code-based route tree in
  `src/app/router.tsx` (no file-based routing). Lazy-load route components
  with `lazyRouteComponent`; gate auth in `beforeLoad`.

## Data And API

- TanStack Query is the data layer. Each `features/*/api/*.ts` file is one
  operation: reads export `queryOptions` factories, `useSuspenseQuery` hooks,
  and structured `queryKeys`; writes export `useMutation` hooks that
  invalidate or seed the cache. Workspace-scoped query keys include the
  workspace slug.
- All requests go through `src/lib/api/client.ts`, which sends credentials,
  the CSRF header, and the `X-Workspace` header. Do not call `fetch` directly
  from features.
- SSE handling lives in `src/features/conversations/stream/`: a hand-written
  parser, a typed versioned event protocol, and a reducer. The parser throws
  on unknown event names, so a new server-side event breaks stale clients —
  ship the client change first.
- The conversation active-run read also returns the latest run outcome so a
  terminal approval expiry can mark its unresolved tool row failed and show
  plain-language outcome copy without keeping the conversation blocked. It
  includes the active approval's expiry deadline; schedule one healing read at
  that deadline instead of polling throughout a days-long wait. An active run
  always takes precedence over an older expiry outcome.
- API types are hand-written per feature in `types.ts`; there is no OpenAPI
  codegen. Use `type` aliases, not `interface` (lint-enforced).
- Forms use native HTML forms plus `FormData` with the helpers in
  `src/lib/forms.ts` and hand-rolled validation models. Do not introduce a
  form or schema-validation library.

## UI

- Components are shadcn (`base-nova` style) built on `@base-ui/react`, with
  Tailwind 4 configured CSS-first in `src/index.css` (no
  `tailwind.config.js`), lucide icons, and `cn()` from `lib/utils.ts`.
  `src/components/ui/` is treated as vendored output (excluded from knip,
  relaxed lint) — prefer adding shadcn components over hand-building
  primitives.
- Keep UI dense, practical, and clear, and write copy for a non-technical
  operator: state outcomes in plain language, lean on defaults instead of
  exposing configuration, and put expert options behind Advanced
  disclosures. Prefer simple, accessible controls over custom widgets.
- Integration-operation audit detail parses only the canonical pending/terminal
  contract. Pending intent must not imply an outcome. Terminal summaries use
  one intent-count line with status badges; concrete effect counts stay in the
  evidence contract and item detail instead of creating a second operator-facing
  summary. Humanize machine tokens such as reason codes before display.
- Schedule completion contracts remain opt-in behind the review step's Advanced
  disclosure. Criteria are one plain-language check per line; do not expose the
  underlying completion JSON or outcome codes in the form. Completion reports
  use the shared compact `ToolResultCard` pattern; keep evidence collapsed by
  default like other rich tool results. Optional request and total-token
  budgets share the same Advanced disclosure and use the platform defaults when
  blank. When the report requirement or a budget is removed, preserve unknown
  completion-contract extension data through schedule edits. Run history names
  the precise tripped budget when bounded evidence contains it. Keep persisted
  budget values within JavaScript's safe-integer range so API-created schedules
  round-trip without numeric loss.
- Integration recovery actions derive from the connection credential's
  `auth_mode`, never from the provider's supported-mode list. OAuth may offer
  sign-in/refresh; API-key and service-account connections offer obscured,
  in-place credential replacement only when the persisted status requests it.
- Per-tool-call UI (approvals, live status, results) renders inline in the
  tool row within the transcript, not as separate blocks.
- Code-mode workflows render as one collapsed outer row whose children recurse
  through the standard `ToolCallRow`; keep live state normalized by parent id,
  rebuild replay only from the persisted nested trace, and auto-expand any
  nested approval so operator consent is never hidden. Label the children as
  tool calls, not workflow steps: interpreter-side filtering, aggregation, and
  branching are meaningful work but are not separate trace children. Prefer a trace's
  structured presentation result over its excerpt so provider presenters work
  after reload. The presentation result is complete relative to the governed
  nested tool return: pagination may control the visible page, but must not
  discard rows, and copy/export actions use the complete retained result. A
  truncated legacy excerpt gets explanatory fallback copy, not malformed JSON.
  Settled workflow rows also expose the complete outer tool result under an
  explicitly labelled model-output disclosure so operators can distinguish
  what the model received from the richer nested results retained for them.
- Complete transcript-only tool results may arrive through the persisted
  tool-return `public_result` metadata while the model-facing content remains
  bounded. Present the complete result rather than its model summary; use the
  shared `DataTable` client pagination for large bounded row sets so copy and
  CSV export still operate over all rows.
- Opaque tool targets render through the shared entity field system in
  `src/components/tool-ui/`: hydrate labels from the conversation-scoped API,
  use the shared Base UI combobox for editable targets, preserve structured
  reference values, and fail closed as “Target unavailable” rather than
  exposing a raw ID.
- Editable record approvals use the server-declared `min_rows` and column
  `required` constraints. Keep editor feedback, approval gating, and decision
  merge on the shared record-validity helper, and give repeated controls
  row-specific accessible names.
- The conversation composer exposes active integration context for both new
  and existing conversations, including for read-only members.
  New-conversation selection stays local until it is submitted atomically with
  the first message.
- In shared workspaces, the Context Group picker hides resources from personal
  connections. Standalone context selection may still show those resources in
  conversations and schedules; do not reuse the group filter for that picker.
- Build the real product interface, not marketing pages, unless the task
  explicitly asks for marketing content. Do not leave default scaffold copy,
  metadata, or assets in user-facing screens.
- Keep frontend environment values explicit with `VITE_*` only — every such
  value is inlined into the browser bundle. Currently the only one is
  `VITE_API_BASE_URL`; there is no Vite dev proxy, the browser calls the API
  origin directly. Production nginx CSP permits browser connections to the API
  and the explicit `WEB_PUBLIC_ASSET_ORIGINS` allowlist so direct cloud-storage
  uploads work without widening `connect-src` to wildcard origins.

## Checks

`pnpm check` is the full gate and what CI runs: typecheck (`tsc -b`), eslint
(zero warnings), vitest, prettier, knip dead-code detection,
dependency-cruiser, and the production build. Run it (or the relevant subset)
before finishing frontend work.

Keep focused unit tests under `apps/web/tests/` using paths that mirror the
source module under test. Do not add colocated frontend tests under
`apps/web/src/`.

```bash
cd apps/web
pnpm install
pnpm check
pnpm dev
```
