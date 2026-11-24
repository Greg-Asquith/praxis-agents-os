# Custom code

- **Status:** Implemented. Core ships both custom directories empty.
- **Rule:** Implementation work follows this note. Record any deviation in
  this note in the same pull request. A deployment feature that needs an edit
  outside the custom directories is a core change, and section 6 applies.
- This note contains **structure, not product scope**. What a deployment
  builds is its own business. Where that code lives and what it may touch is
  the business of this note.

## 1. The problem this solves

Each customer runs their own clone of this repository. A deployment adds
tools that only that customer needs, such as a report builder or a dashboard
over their warehouse. When that code sits among core modules, every upstream
merge risks a conflict, and deployment code can leak back into core.

Goals, in priority order:

1. **A deployment changes only its custom directories.** Core files stay
   identical to upstream, so merging upstream is routine.
2. **Core never depends on custom code.** Core builds, runs, and passes its
   checks with both directories empty.
3. **No governance regression.** Custom tools, routes, and jobs use the same
   registry, dispatch, role checks, tenancy, and audit as core code.

## 2. Where custom code lives

| Kind | Location |
| --- | --- |
| Backend code | `apps/api/custom/` |
| Backend tests | `apps/api/tests/custom/` |
| Migrations | `apps/api/alembic/versions/app/` (the Alembic `app` branch) |
| Web code | `apps/web/src/custom/` |
| Web tests | `apps/web/tests/custom/` |
| Documentation | `docs/custom/` |

Core owns everything else. Core adds no file to these locations other than
the seam stubs in section 3 and the first `app` migration, which creates the
`app` schema.

## 3. Seams

Core reaches custom code through a fixed set of named imports. Each seam is a
plain import, so type checkers and the import-law checks see it.

### 3.1 Backend

| Custom module | Export | Core caller |
| --- | --- | --- |
| `custom.routes` | `router` | `routes/__init__.py` mounts it under the `/custom` prefix |
| `custom.models` | Model imports | `models/__init__.py` imports it last |
| `custom.runtime` | `register_custom_runtime()` | `assemble_runtime_catalogs()` calls it after core tools and enabled providers |
| `custom.hooks` | Three hook functions | Sign-in, workspace creation, and membership changes |

- Every custom API route is served under `/custom`, so it can't shadow a core
  route.
- Custom agent tools use the `runtime_tool` decorator and custom jobs use the
  generic jobs registry. A duplicate tool name or job kind fails at boot.
- Custom settings live in a `BaseSettings` class inside the package, the way
  a provider package keeps its own settings.

The hooks run inside the core transaction, and an exception fails the
operation:

| Hook | Core calls it |
| --- | --- |
| `after_sign_in` | When a user completes a full sign-in, after any two-factor step |
| `after_workspace_created` | When a workspace is created, with tenant context set to it |
| `before_membership_change` | Before a membership changes role or is removed. Raise `AuthorizationError` to reject the change |

### 3.2 Public links

Core reserves two prefixes for custom links that open without sign-in:

- **API:** `/custom/public/{token}/...` under the API prefix. Core replaces
  the token in request logs, security events, and error reports, counts every
  path below one token template as one rate-limit key, and sets
  `Cache-Control: private, no-store` and `X-Robots-Tag: noindex, nofollow` on
  every response, including errors.
- **Web:** `/share/...`. The production nginx configuration serves the app
  shell there without an access log and tells search engines to skip it.

The custom route still validates the token, limits what it returns, and
supports revoking the link.

### 3.3 Web

Core imports only the `src/custom/index.ts` file, from four files:

| Export | Core caller |
| --- | --- |
| `useCustomTools()` | `src/routes/tools.tsx` and `src/components/shell/primary-navigation.tsx` |
| `customAppRoutes(appRoute)` | `src/app/router.tsx` |
| `customPublicRoutes(rootRoute)` | `src/app/router.tsx` |
| `customToolRowPresenters` | The conversation tool row registry |

- The Tools page at `/tools` belongs to core. It lists the entries that
  `useCustomTools()` returns, and the sidebar shows **Tools** only when that
  list isn't empty. The hook decides what each user sees, for example from a
  query against a custom API route.
- Signed-in custom routes sit under `/tools/`. Public custom routes sit under
  `/share/`. Core owns every other path.
- Core presenters match before custom presenters, so a custom presenter can't
  replace a core tool card.
- The `CustomTool` type lives in `src/lib/custom-contract.ts`, outside the
  custom directory, because core owns it.

## 4. Import laws (enforced)

1. Core imports the backend `custom` package only in the files that the
   import-law test names, and each file names exactly one seam module from
   section 3.1.
2. Custom backend code may import core packages. It doesn't import provider
   packages under `integrations/`.
3. Core web code imports `src/custom/` only from the four files in section
   3.3, and only its `index.ts` file.
4. Custom web code may import core modules other than `src/app/`. It reaches
   provider UI only through the integration registry or contract.

Enforcement:

- `apps/api/tests/contract/test_custom_import_laws.py` walks the backend AST
  and asserts laws 1 and 2.
- `apps/web/.dependency-cruiser.cjs` asserts laws 3 and 4 in `pnpm arch`.
- `apps/web/tests/custom/route-namespace.test.ts` asserts the route prefixes.

Don't widen a seam list to make a core feature depend on custom code. Add a
seam only when custom code needs a new way to contribute, and record it here.

## 5. Security

The custom directories change where code lives, not what it may do:

- Scope every custom query to the active workspace, and give every custom
  route a role dependency.
- A custom table that holds workspace data enables and forces row-level
  security in its creating migration, with a blindness test under
  `tests/custom/`.
- A public custom route lives under the reserved prefixes in section 3.2 and
  never returns workspace data without a capability check.
- A hook runs with the access of the core operation that calls it. Write an
  audit record for any access a hook grants.

## 6. Changes that still belong to core

Some deployment needs change core behaviour and have no seam. Examples are fields on the
current-user response, new Python or npm dependencies, deploy scripts, and
branding.

Handle each one in this order:

1. Prefer a custom route or a custom hook that gives the same outcome without
   a core edit.
2. Otherwise make the change upstream as a general capability or a new seam.
3. As a last resort, patch core in the deployment, and list the patch in
   `docs/custom/` so the next upstream merge accounts for it.
