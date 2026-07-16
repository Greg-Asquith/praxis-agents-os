// apps/web/src/routes/app-layout-fallback.tsx

import { Skeleton } from "@/components/ui/skeleton"

export function AppLayoutFallback() {
  return (
    <div className="bg-sidebar text-foreground h-dvh overflow-hidden md:grid md:grid-cols-[280px_minmax(0,1fr)]">
      <aside className="bg-sidebar hidden h-dvh min-h-0 md:flex md:flex-col">
        <div className="flex h-14 shrink-0 items-center px-4">
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

      <div className="flex h-dvh min-h-0 min-w-0 flex-col p-0 md:p-2 md:pl-0">
        <div className="bg-background border-border/60 flex min-h-0 flex-1 flex-col overflow-hidden rounded-none border-0 shadow-none md:rounded-xl md:border md:shadow-sm">
          <header className="flex h-12 shrink-0 items-center gap-3 border-b px-4">
            <Skeleton className="size-8 rounded-lg md:hidden" />
            <div className="flex min-w-0 flex-1 items-center gap-2">
              <Skeleton className="h-4 w-20" />
              <Skeleton className="h-4 w-32" />
            </div>
            <Skeleton className="hidden h-10 w-60 rounded-lg md:block lg:w-72" />
          </header>
          <main className="min-h-0 min-w-0 flex-1 overflow-hidden px-6 py-5">
            <div className="flex h-full flex-col gap-4">
              <Skeleton className="h-8 w-64 max-w-full" />
              <Skeleton className="h-28 w-full rounded-xl" />
              <Skeleton className="min-h-0 flex-1 rounded-xl" />
            </div>
          </main>
        </div>
      </div>
    </div>
  )
}
