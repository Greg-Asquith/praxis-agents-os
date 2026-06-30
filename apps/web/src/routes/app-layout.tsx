// apps/web/src/routes/app-layout.tsx

import { Suspense } from "react"
import { Outlet } from "@tanstack/react-router"

import { AppShell } from "@/components/shell/app-shell"
import { Skeleton } from "@/components/ui/skeleton"
import { ActiveWorkspaceProvider } from "@/features/workspaces/components/active-workspace-provider"

function AppLayoutFallback() {
  return (
    <div className="bg-background flex min-h-screen">
      <div className="bg-sidebar hidden w-64 border-r p-4 md:flex md:flex-col md:gap-4">
        <Skeleton className="h-8 w-36" />
        <Skeleton className="h-8 w-full" />
        <Skeleton className="h-8 w-full" />
      </div>
      <main className="flex flex-1 flex-col gap-4 p-6">
        <Skeleton className="h-9 w-64" />
        <Skeleton className="h-36 w-full" />
        <Skeleton className="h-64 w-full" />
      </main>
    </div>
  )
}

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
