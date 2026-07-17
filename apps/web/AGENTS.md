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
- Per-tool-call UI (approvals, live status, results) renders inline in the
  tool row within the transcript, not as separate blocks.
- Build the real product interface, not marketing pages, unless the task
  explicitly asks for marketing content. Do not leave default scaffold copy,
  metadata, or assets in user-facing screens.
- Keep frontend environment values explicit with `VITE_*` only — every such
  value is inlined into the browser bundle. Currently the only one is
  `VITE_API_BASE_URL`; there is no Vite dev proxy, the browser calls the API
  origin directly.

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
