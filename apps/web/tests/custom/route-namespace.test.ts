// apps/web/tests/custom/route-namespace.test.ts

import { createRootRoute, createRouter, type AnyRoute } from "@tanstack/react-router"
import { describe, expect, it } from "vitest"

import { customAppRoutes, customPublicRoutes } from "@/custom"

function pathsOutside(prefix: string, root: AnyRoute, routes: readonly AnyRoute[]) {
  const router = createRouter({ routeTree: root.addChildren([...routes]) })
  return Object.keys(router.routesByPath).filter((path) => !path.startsWith(prefix))
}

// Core owns every other path, so a deployment route can never shadow a core one.
describe("custom route namespaces", () => {
  it("keeps signed-in custom routes under /tools/", () => {
    const root = createRootRoute()
    expect(pathsOutside("/tools/", root, customAppRoutes(root))).toEqual([])
  })

  it("keeps public custom routes under /share/", () => {
    const root = createRootRoute()
    expect(pathsOutside("/share/", root, customPublicRoutes(root))).toEqual([])
  })
})
