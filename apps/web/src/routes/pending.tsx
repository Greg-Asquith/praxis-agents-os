// apps/web/src/routes/pending.tsx

import { Skeleton } from "@/components/ui/skeleton"

export function PendingRoute() {
  return (
    <div className="bg-background flex min-h-screen flex-col gap-3 p-6">
      <Skeleton className="h-8 w-48" />
      <Skeleton className="h-24 w-full" />
      <Skeleton className="h-64 w-full" />
    </div>
  )
}
