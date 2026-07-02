// apps/web/src/routes/app-layout-fallback.tsx

import { Skeleton } from "@/components/ui/skeleton"

export function AppLayoutFallback() {
  return (
    <div className="bg-background text-foreground h-dvh overflow-hidden md:grid md:grid-cols-[280px_minmax(0,1fr)]">
      <aside className="bg-sidebar hidden h-dvh min-h-0 border-r md:flex md:flex-col">
        <div className="flex h-14 shrink-0 items-center border-b px-4">
          <div className="flex min-w-0 items-center gap-3 px-1">
            <Skeleton className="size-8 rounded-lg" />
            <div className="flex min-w-0 flex-col gap-1.5">
              <Skeleton className="h-3.5 w-24" />
              <Skeleton className="h-3 w-16" />
            </div>
          </div>
        </div>
        <div className="flex min-h-0 flex-1 flex-col gap-3 p-3">
          <div className="flex shrink-0 flex-col gap-1">
            <Skeleton className="h-8 w-full rounded-lg" />
            <Skeleton className="h-8 w-full rounded-lg" />
            <Skeleton className="h-8 w-full rounded-lg" />
            <Skeleton className="h-8 w-full rounded-lg" />
          </div>
          <Skeleton className="h-px w-full" />
          <div className="flex min-h-0 flex-1 flex-col gap-2">
            <Skeleton className="h-4 w-28" />
            <Skeleton className="h-11 w-full rounded-lg" />
            <Skeleton className="h-11 w-full rounded-lg" />
            <Skeleton className="h-11 w-full rounded-lg" />
          </div>
        </div>
        <div className="shrink-0 border-t p-3">
          <Skeleton className="h-12 w-full rounded-lg" />
        </div>
      </aside>

      <div className="flex h-dvh min-h-0 min-w-0 flex-col">
        <header className="bg-background/95 flex h-14 shrink-0 items-center gap-3 border-b px-4 md:px-6">
          <Skeleton className="size-8 rounded-lg md:hidden" />
          <div className="flex min-w-0 flex-1 items-center gap-2">
            <Skeleton className="h-4 w-20" />
            <Skeleton className="h-4 w-32" />
          </div>
          <Skeleton className="hidden h-10 w-60 rounded-lg md:block lg:w-72" />
        </header>
        <main className="min-h-0 min-w-0 flex-1 overflow-hidden p-4 md:p-6">
          <div className="flex h-full flex-col gap-4">
            <Skeleton className="h-8 w-64 max-w-full" />
            <Skeleton className="h-28 w-full rounded-xl" />
            <Skeleton className="min-h-0 flex-1 rounded-xl" />
          </div>
        </main>
      </div>
    </div>
  )
}
