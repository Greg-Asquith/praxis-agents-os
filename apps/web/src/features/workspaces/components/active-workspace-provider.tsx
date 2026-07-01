// apps/web/src/features/workspaces/components/active-workspace-provider.tsx

import { useEffect, useMemo, useState, type ReactNode } from "react"
import { useSuspenseQuery } from "@tanstack/react-query"

import { currentUserQueryOptions } from "@/features/auth/api/get-current-user"
import { useWorkspacesQuery } from "@/features/workspaces/api/list-workspaces"
import type { Workspace } from "@/features/workspaces/types"
import { ActiveWorkspaceContext } from "@/features/workspaces/components/active-workspace-context"
import { setActiveWorkspaceSlug } from "@/features/workspaces/workspace-context"

const STORAGE_KEY = "praxis.activeWorkspaceSlug"

function readStoredSlug() {
  if (typeof window === "undefined") {
    return null
  }

  return window.localStorage.getItem(STORAGE_KEY)
}

function storeSlug(slug: string) {
  if (typeof window !== "undefined") {
    window.localStorage.setItem(STORAGE_KEY, slug)
  }
}

function chooseWorkspace(
  workspaces: Workspace[],
  defaultWorkspaceId: string | null,
  preferredSlug: string | null
) {
  return (
    workspaces.find((workspace) => workspace.slug === preferredSlug) ??
    workspaces.find((workspace) => workspace.id === defaultWorkspaceId) ??
    workspaces[0] ??
    null
  )
}

export function ActiveWorkspaceProvider({ children }: { children: ReactNode }) {
  const { data: user } = useSuspenseQuery(currentUserQueryOptions())
  const { data } = useWorkspacesQuery()
  const workspaces = data.workspaces
  const [activeSlug, setActiveSlug] = useState(() => readStoredSlug())

  const activeWorkspace = useMemo(
    () => chooseWorkspace(workspaces, user.default_workspace_id, activeSlug),
    [activeSlug, user.default_workspace_id, workspaces]
  )

  // Sync the request-layer slug during render, not in an effect, so requests fired by children (including suspense reads) always carry the resolved workspace before the first one goes out.
  setActiveWorkspaceSlug(activeWorkspace?.slug ?? null)

  useEffect(() => {
    if (activeWorkspace) {
      storeSlug(activeWorkspace.slug)
    }
  }, [activeWorkspace])

  const value = useMemo(() => {
    if (!activeWorkspace) {
      return null
    }

    return {
      workspace: activeWorkspace,
      workspaces,
      setWorkspaceBySlug: setActiveSlug,
    }
  }, [activeWorkspace, workspaces])

  if (!value) {
    return (
      <div className="bg-background text-muted-foreground flex min-h-screen items-center justify-center p-6 text-sm">
        No workspace is available for this account.
      </div>
    )
  }

  return <ActiveWorkspaceContext value={value}>{children}</ActiveWorkspaceContext>
}
