// apps/web/src/features/conversations/components/tool-activity-status.tsx

import {
  BotIcon,
  CheckCircle2Icon,
  CircleDashedIcon,
  ShieldAlertIcon,
  TriangleAlertIcon,
  WrenchIcon,
} from "lucide-react"

import type { DelegationToolActivity, ToolActivity } from "@/features/conversations/message-parts"
import { cn } from "@/lib/utils"

type ActivityStatus = ToolActivity["status"] | DelegationToolActivity["status"]
type FallbackIcon = "delegation" | "tool"

export function ActivityStatusIcon({
  fallbackIcon,
  status,
}: {
  fallbackIcon: FallbackIcon
  status: ActivityStatus
}) {
  const className = cn(
    "size-3.5 shrink-0",
    status === "failed" || status === "denied" ? "text-destructive" : "text-muted-foreground",
    status === "running" && "animate-spin"
  )

  if (status === "awaiting_approval") {
    return <ShieldAlertIcon className={className} />
  }
  if (status === "failed" || status === "denied") {
    return <TriangleAlertIcon className={className} />
  }
  if (status === "completed") {
    return <CheckCircle2Icon className={className} />
  }
  if (status === "running") {
    return <CircleDashedIcon className={className} />
  }
  if (fallbackIcon === "delegation") {
    return <BotIcon className={className} />
  }
  return <WrenchIcon className={className} />
}

export function ActivityStatusSuffix({
  status,
  suffix,
}: {
  status: ActivityStatus
  suffix: string | null
}) {
  if (!suffix) {
    return null
  }

  return (
    <span
      className={cn(
        "shrink-0 text-xs",
        status === "failed" || status === "denied" ? "text-destructive" : "text-muted-foreground"
      )}
    >
      {suffix}
    </span>
  )
}
