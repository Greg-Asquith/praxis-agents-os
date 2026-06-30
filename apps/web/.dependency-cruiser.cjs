/** @type {import("dependency-cruiser").IConfiguration} */
module.exports = {
  forbidden: [
    {
      name: "no-circular",
      severity: "error",
      comment: "Circular dependencies make app behavior harder to reason about.",
      from: {},
      to: { circular: true },
    },
    {
      name: "ui-components-stay-generic",
      severity: "error",
      comment: "Shared UI primitives must not depend on app, route, feature, or config code.",
      from: { path: "^src/components/ui/" },
      to: { path: "^src/(app|routes|features|config)/" },
    },
    {
      name: "api-client-stays-framework-light",
      severity: "error",
      comment: "API helpers should stay usable outside React components and routes.",
      from: { path: "^src/lib/api/" },
      to: { path: "^src/(app|routes|features|components)/" },
    },
    {
      name: "config-has-no-runtime-app-dependencies",
      severity: "error",
      comment: "Configuration should be plain data and environment parsing.",
      from: { path: "^src/config/" },
      to: { path: "^src/(app|routes|features|components)/" },
    },
    {
      name: "features-do-not-import-route-shell",
      severity: "error",
      comment:
        "Feature modules should expose behavior upward instead of reaching into route shells.",
      from: { path: "^src/features/" },
      to: { path: "^src/(app|routes)/" },
    },
    {
      name: "routes-do-not-import-app-bootstrap",
      severity: "error",
      comment: "Route modules should not depend on app bootstrapping internals.",
      from: { path: "^src/routes/" },
      to: { path: "^src/app/" },
    },
  ],
  options: {
    doNotFollow: {
      path: "node_modules",
    },
    enhancedResolveOptions: {
      conditionNames: ["import", "types", "browser", "default"],
      exportsFields: ["exports"],
      extensions: [".ts", ".tsx", ".js", ".jsx", ".json"],
    },
    tsConfig: {
      fileName: "tsconfig.app.json",
    },
  },
}
