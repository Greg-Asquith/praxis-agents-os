# Frontend guidelines

Vite, React 19, strict TypeScript, Tailwind CSS 4, and `pnpm`. The frontend
is a single-page app with no server runtime. Follow the
[repository guidelines](../../AGENTS.md). Paths below are relative to
`apps/web/` unless stated otherwise.

## Structure

Follow the existing layout and dependency boundaries:

- `src/app/` is bootstrap only (App, router, query client); `src/config/` is
  plain data and env parsing; `src/lib/` holds framework-light helpers
  including the API client; `src/components/ui/` holds shadcn primitives,
  with shared form and shell composition in `src/components/forms/` and
  `src/components/shell/`; `src/routes/` holds top-level route shells.
- Feature code lives in `src/features/<feature>/` with `api/`, `components/`,
  `routes/`, and a feature-local `types.ts`. Follow this layout for new
  features.
- Layering is enforced by `.dependency-cruiser.cjs` (`pnpm arch`): no cycles;
  `components/ui` stays generic; `lib/api` stays framework-light; integration
  packages may use the published UI, tool UI, and Markdown component seams;
  shared components and application layers reach provider packages only through
  the integration registry or contract; features do not import route shells;
  routes do not import `app/`.
  Fix violations by restructuring, not by editing the rules.
- Routing is TanStack Router with a code-based route tree in
  `src/app/router.tsx` (no file-based routing). Lazy-load route components
  with `lazyRouteComponent`; gate auth in `beforeLoad`.

## Data and API

Use the shared request and state conventions:

- TanStack Query is the data layer. Each `features/*/api/*.ts` file is one
  operation: reads export `queryOptions` factories, `useSuspenseQuery` hooks,
  and structured `queryKeys`; writes export `useMutation` hooks that
  invalidate or seed the cache. Workspace-scoped query keys include the
  workspace slug.
- All requests go through `src/lib/api/client.ts`, which sends credentials,
  the CSRF header, and the `X-Workspace` header. Do not call `fetch` directly
  from features.
- `apiRequest<T>` trusts same-origin API JSON and types it with the
  feature-owned response `type`. Treat URL and state payloads, SSE frames,
  retained tool arguments and results, credential JSON, and integration
  payloads as `unknown` until a feature guard or `src/lib/guards.ts` proves
  their shape.
- Use `apiRequestNoContent` for endpoints that return no content. Use the
  shared `isOneOf` guard to narrow values against a closed string set.
- API types are hand-written per feature in `types.ts`; there is no OpenAPI
  codegen. Use `type` aliases, not `interface` (lint-enforced).
- Forms use native HTML forms plus `FormData` with the helpers in
  `src/lib/forms.ts` and hand-rolled validation models. Do not introduce a
  form or schema-validation library.

## UI

Build for a non-technical operator:

- Components are shadcn (`base-nova` style) built on `@base-ui/react`, with
  Tailwind 4 configured CSS-first in `src/index.css` (no
  `tailwind.config.js`), lucide icons, and `cn()` from `lib/utils.ts`.
  `src/components/ui/` is treated as vendored output (excluded from knip,
  relaxed lint). Prefer adding shadcn components over hand-building
  primitives.
- Keep UI dense, practical, and clear, and write copy for a non-technical
  operator: state outcomes in plain language, lean on defaults instead of
  exposing configuration, and put expert options behind Advanced
  disclosures. Prefer simple, accessible controls over custom widgets.
- Build the real product interface, not marketing pages, unless the task
  explicitly asks for marketing content. Do not leave default scaffold copy,
  metadata, or assets in user-facing screens.
- Keep frontend environment values explicit with `VITE_*` only. Every such
  value is inlined into the browser bundle. The only one is
  `VITE_API_BASE_URL`; there is no Vite dev proxy, the browser calls the API
  origin directly. Production nginx CSP permits browser connections to the API
  and the explicit `WEB_PUBLIC_ASSET_ORIGINS` allowlist so direct cloud-storage
  uploads work without widening `connect-src` to wildcard origins.

## Read for your task

Before editing a domain, read its implementation reference. Paths in this
table are relative to this file:

| Change area                                                  | Required reference                                                                            |
| ------------------------------------------------------------ | --------------------------------------------------------------------------------------------- |
| Integration connections, recovery, or provider presenters    | [Integration guide and provider references](../../docs/implementation/integrations/README.md) |
| Conversation streaming, recovery, context, or schedules      | [Agent runs](../../docs/implementation/agent-runs.md)                                         |
| Approval fields, entity editors, tool results, or artifacts  | [Tool dispatch](../../docs/implementation/tool-dispatch.md)                                   |
| Workflow rows and nested approval replay                     | [Code Mode](../../docs/implementation/code-mode.md)                                           |
| Native tool results, generated files, or classifier settings | [Native helper tools](../../docs/implementation/native-tools.md)                              |
| File links and uploads                                       | [Storage and files](../../docs/implementation/storage-and-files.md)                           |
| Authentication redirects or audit presentation               | [Security](../../docs/implementation/security.md)                                             |
| Knowledge Base imports or refresh                            | [Knowledge sources](../../docs/implementation/knowledge-sources.md)                           |
| Model transport labels                                       | [Model providers](../../docs/implementation/model-providers.md)                               |

## Verification

`pnpm check` is the full gate and what CI runs: typecheck (`tsc -b`), eslint
(zero warnings), vitest, prettier, knip dead-code detection,
dependency-cruiser, and the production build. Run it (or the relevant subset)
before finishing frontend work.

Keep focused unit tests under `apps/web/tests/` using paths that mirror the
source module under test. Do not add colocated frontend tests under
`apps/web/src/`.

From the repository root, enter the web app to install, verify, or develop:

```bash
cd apps/web
pnpm install
pnpm check
pnpm dev
```
