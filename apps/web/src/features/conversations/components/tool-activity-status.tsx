// apps/web/src/features/conversations/components/tool-activity-status.tsx

import {
  BotIcon,
  CheckCircle2Icon,
  CircleDashedIcon,
  ShieldAlertIcon,
  TriangleAlertIcon,
  WrenchIcon,
} from "lucide-react"

import { Badge } from "@/components/ui/badge"
import type { DelegationToolActivity, ToolActivity } from "@/features/conversations/message-parts"
import { useElapsedSeconds } from "@/features/conversations/hooks/use-elapsed-seconds"
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
    statusColor(status),
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
  liveRunning = false,
  status,
  suffix,
}: {
  liveRunning?: boolean
  status: ActivityStatus
  suffix: string | null
}) {
  if (!suffix && !liveRunning) {
    return null
  }

  return (
    <span className={cn("ml-auto shrink-0 text-right text-xs", statusColor(status))}>
      {suffix}
      {liveRunning ? <ElapsedSeconds running={status === "running"} /> : null}
    </span>
  )
}

export function ActivityStatusBadge({
  liveRunning = false,
  status,
}: {
  liveRunning?: boolean
  status: ActivityStatus
}) {
  const label = statusLabel(status)
  const content = (
    <>
      {label}
      {liveRunning ? <ElapsedSeconds running={status === "running"} /> : null}
    </>
  )

  if (status === "completed") {
    return <Badge variant="success">{content}</Badge>
  }
  if (status === "awaiting_approval") {
    return <Badge variant="warning">{content}</Badge>
  }
  if (status === "failed" || status === "denied") {
    return <Badge variant="destructive">{content}</Badge>
  }
  return <Badge variant="secondary">{content}</Badge>
}

function ElapsedSeconds({ running }: { running: boolean }) {
  const elapsedSeconds = useElapsedSeconds(running)

  return <span> · {String(elapsedSeconds)}s</span>
}

function statusColor(status: ActivityStatus) {
  if (status === "awaiting_approval") {
    return "text-warning"
  }
  if (status === "completed") {
    return "text-success"
  }
  if (status === "failed" || status === "denied") {
    return "text-destructive"
  }
  return "text-muted-foreground"
}

function statusLabel(status: ActivityStatus) {
  if (status === "awaiting_approval") {
    return "Waiting"
  }
  if (status === "completed") {
    return "Done"
  }
  if (status === "failed") {
    return "Failed"
  }
  if (status === "denied") {
    return "Declined"
  }
  if (status === "running") {
    return "Running"
  }
  return "Unknown"
}
