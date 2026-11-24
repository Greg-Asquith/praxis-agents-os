// apps/web/src/custom/index.ts

import type { AnyRoute } from "@tanstack/react-router"

import type { ToolRowPresenter } from "@/integrations/contract"
import type { CustomTool } from "@/lib/custom-contract"

// The four exports below are the seams core imports. Keep their names; change their bodies.

const NO_TOOLS: readonly CustomTool[] = []

/** Returns the tools the current user can open. The Tools page and sidebar list them. */
// eslint-disable-next-line react-x/no-unnecessary-use-prefix -- A deployment reads its own queries here.
export function useCustomTools(): readonly CustomTool[] {
  return NO_TOOLS
}

/** Creates the signed-in routes, each under `/tools/`. Leave the return type inferred. */
export function customAppRoutes(_appRoute: AnyRoute) {
  return [] as const
}

/** Creates the routes open without sign-in, each under `/share/`. */
export function customPublicRoutes(_rootRoute: AnyRoute) {
  return [] as const
}

/** Conversation cards for the deployment's agent tools. */
export const customToolRowPresenters: readonly ToolRowPresenter[] = []
