// apps/web/src/routes/route-pending.tsx

import { Skeleton } from "@/components/ui/skeleton"

export function RoutePendingFallback() {
  return (
    <div className="flex h-full min-h-0 items-center justify-center">
      <Skeleton className="h-8 w-32 rounded-lg" />
    </div>
  )
}
