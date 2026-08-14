// apps/web/src/features/usage/components/usage-empty-state.tsx

import { ActivityIcon } from "lucide-react"

import { EmptyState } from "@/components/ui/empty-state"

export function UsageEmptyState() {
  return (
    <EmptyState
      description="Data collection began when usage metering landed. This view will fill as your team works with agents and AI tools."
      icon={<ActivityIcon className="size-5" />}
      title="No AI usage in this period"
    />
  )
}
