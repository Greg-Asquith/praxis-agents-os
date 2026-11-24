# Custom code

This directory holds the web code that belongs to one deployment. Core ships it
empty. A deployment fills it in and can change anything inside it without
touching core code, so upstream merges stay clean.

Read [custom code](../../../../docs/architecture/custom-code.md) for the design
and the boundary rules before you add code here.

## Seams

Core imports only the `index.ts` file, and only these exports:

| Export                          | Used by                                          |
| ------------------------------- | ------------------------------------------------ |
| `useCustomTools()`              | The Tools page and the sidebar                   |
| `customAppRoutes(appRoute)`     | The router, for signed-in routes under `/tools/` |
| `customPublicRoutes(rootRoute)` | The router, for public routes under `/share/`    |
| `customToolRowPresenters`       | The conversation tool row registry               |

## Layout

Group code by tool below `index.ts`, with the same shape as a core feature:

```
src/custom/
  index.ts
  REPORTS/
    api/
    components/
    routes/
    types.ts
```

- Call the deployment's API routes under `/custom/` through `src/lib/api/client.ts`.
- Public routes under `/share/` are served without an access log, so a link
  token in the path isn't recorded.
- Put tests in `tests/custom/`, mirroring the source path.
- Build each route with `createRoute` and the parent the router passes in, and
  load its component with `lazyRouteComponent`. Type the parent as a generic
  and leave the return type inferred, so links to your routes stay typed:

  ```tsx
  export function customAppRoutes<TParent extends AnyRoute>(appRoute: TParent) {
    const reports = createRoute({ getParentRoute: () => appRoute, path: "/tools/reports" })
    return [reports] as const
  }
  ```
