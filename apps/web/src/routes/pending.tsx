// apps/web/src/routes/pending.tsx

import { Skeleton } from "@/components/ui/skeleton"
import { AppLayoutFallback } from "@/routes/app-layout"
import { currentPathname, isAuthRecoveryPath } from "@/routes/recovery-paths"

export function PendingRoute() {
  if (!isAuthRecoveryPath(currentPathname())) {
    return <AppLayoutFallback />
  }

  return <AuthPendingFallback />
}

function AuthPendingFallback() {
  return (
    <main className="bg-background grid min-h-screen lg:grid-cols-[minmax(0,0.9fr)_minmax(420px,0.55fr)]">
      <section className="bg-muted/30 hidden border-r p-8 lg:flex lg:flex-col lg:justify-between">
        <div className="flex items-center gap-3">
          <Skeleton className="size-8 rounded-lg" />
          <Skeleton className="h-4 w-36" />
        </div>
        <div className="max-w-xl">
          <Skeleton className="h-4 w-32" />
          <Skeleton className="mt-3 h-24 max-w-lg rounded-xl" />
        </div>
      </section>
      <section className="flex min-h-screen items-center justify-center p-6">
        <div className="flex w-full max-w-md flex-col gap-3">
          <Skeleton className="h-8 w-32" />
          <Skeleton className="h-11 w-full" />
          <Skeleton className="h-11 w-full" />
          <Skeleton className="h-8 w-full" />
        </div>
      </section>
    </main>
  )
}
