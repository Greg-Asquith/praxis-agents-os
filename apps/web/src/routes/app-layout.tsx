// apps/web/src/routes/app-layout.tsx

import { Suspense } from "react"
import { Outlet } from "@tanstack/react-router"

import { AppShell } from "@/components/shell/app-shell"
import { ActiveWorkspaceProvider } from "@/features/workspaces/components/active-workspace-provider"
import { AppLayoutFallback } from "@/routes/app-layout-fallback"

export function AppLayoutRoute() {
  return (
    <Suspense fallback={<AppLayoutFallback />}>
      <ActiveWorkspaceProvider>
        <AppShell>
          <Outlet />
        </AppShell>
      </ActiveWorkspaceProvider>
    </Suspense>
  )
}
