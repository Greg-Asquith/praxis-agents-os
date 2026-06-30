// apps/web/src/features/workspaces/components/active-workspace-context.ts

import { createContext } from "react"

import type { Workspace } from "@/features/workspaces/types"

export type ActiveWorkspaceContextValue = {
  workspace: Workspace
  workspaces: Workspace[]
  setWorkspaceBySlug: (slug: string) => void
}

export const ActiveWorkspaceContext = createContext<ActiveWorkspaceContextValue | null>(null)
