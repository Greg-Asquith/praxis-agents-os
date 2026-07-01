// apps/web/src/features/conversations/components/tool-call-row.tsx

import {
  CheckCircle2Icon,
  CircleDashedIcon,
  ShieldAlertIcon,
  TriangleAlertIcon,
  WrenchIcon,
} from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { runtimeToolLabel } from "@/features/agents/runtime-tools"
import { supportIdentifier } from "@/features/conversations/format"
import type { ToolActivity } from "@/features/conversations/message-parts"
import { safeJsonPreview } from "@/features/conversations/message-parts"
import { cn } from "@/lib/utils"

type ToolCallRowProps = {
  activity: ToolActivity
  compact?: boolean
}

export function ToolCallRow({ activity, compact = false }: ToolCallRowProps) {
  const toolLabel = runtimeToolLabel(activity.name)
  const title = toolLabel ?? "Tool call"
  const supportLabel = toolLabel ? null : supportIdentifier(activity.name)
  const hasArgs = activity.args !== undefined && activity.args !== null
  const hasResult = activity.result !== undefined && activity.result !== null

  return (
    <div
      className={cn(
        "border-border/80 bg-muted/30 flex min-w-0 flex-col gap-2 rounded-lg border px-3 py-2 text-sm",
        compact && "px-2 py-1.5 text-xs"
      )}
    >
      <div className="flex min-w-0 items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <ToolActivityIcon activity={activity} />
          <div className="min-w-0" title={toolLabel ? `Tool: ${activity.name}` : undefined}>
            <p className="truncate font-medium">{title}</p>
            {supportLabel && (
              <p className="text-muted-foreground truncate font-mono text-xs">
                Tool {supportLabel}
              </p>
            )}
          </div>
        </div>
        <Badge variant={badgeVariantForActivity(activity)}>{statusLabel(activity)}</Badge>
      </div>

      {(hasArgs || hasResult) && (
        <div className="grid gap-2 md:grid-cols-2">
          {hasArgs && <JsonDisclosure label="Arguments" value={activity.args} />}
          {hasResult && <JsonDisclosure label="Result" value={activity.result} />}
        </div>
      )}
    </div>
  )
}

function JsonDisclosure({ label, value }: { label: string; value: unknown }) {
  return (
    <details className="group/details min-w-0">
      <summary className="text-muted-foreground hover:text-foreground cursor-pointer text-xs font-medium">
        {label}
      </summary>
      <pre className="bg-background mt-2 max-h-64 overflow-auto rounded-md border p-2 text-xs leading-relaxed whitespace-pre-wrap">
        {safeJsonPreview(value)}
      </pre>
    </details>
  )
}

function ToolActivityIcon({ activity }: { activity: ToolActivity }) {
  if (activity.status === "awaiting_approval") {
    return <ShieldAlertIcon className="text-muted-foreground size-4 shrink-0" />
  }
  if (activity.status === "failed" || activity.status === "denied") {
    return <TriangleAlertIcon className="text-muted-foreground size-4 shrink-0" />
  }
  if (activity.status === "completed") {
    return <CheckCircle2Icon className="text-muted-foreground size-4 shrink-0" />
  }
  if (activity.status === "running") {
    return <CircleDashedIcon className="text-muted-foreground size-4 shrink-0" />
  }
  return <WrenchIcon className="text-muted-foreground size-4 shrink-0" />
}

function statusLabel(activity: ToolActivity) {
  if (activity.status === "awaiting_approval") {
    return "Waiting"
  }
  if (activity.status === "completed") {
    return "Done"
  }
  if (activity.status === "failed") {
    return "Failed"
  }
  if (activity.status === "denied") {
    return "Denied"
  }
  if (activity.status === "running") {
    return "Running"
  }
  return "Unknown"
}

function badgeVariantForActivity(activity: ToolActivity) {
  if (activity.status === "failed" || activity.status === "denied") {
    return "destructive" as const
  }
  if (activity.status === "awaiting_approval") {
    return "secondary" as const
  }
  if (activity.status === "completed") {
    return "outline" as const
  }
  return "secondary" as const
}
