// apps/web/src/features/workspaces/components/use-active-workspace.ts

import { use } from "react"

import { ActiveWorkspaceContext } from "@/features/workspaces/components/active-workspace-context"

export function useActiveWorkspace() {
  const context = use(ActiveWorkspaceContext)
  if (!context) {
    throw new Error("useActiveWorkspace must be used within ActiveWorkspaceProvider")
  }

  return context
}
