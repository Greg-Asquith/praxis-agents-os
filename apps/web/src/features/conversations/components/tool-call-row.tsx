// apps/web/src/features/conversations/components/tool-call-row.tsx

import {
  CheckCircle2Icon,
  ChevronRightIcon,
  CircleDashedIcon,
  ShieldAlertIcon,
  TriangleAlertIcon,
  WrenchIcon,
} from "lucide-react"

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
  const expandable = hasArgs || hasResult
  const textSize = compact ? "text-xs" : "text-sm"

  const header = (
    <>
      <ChevronRightIcon
        className={cn(
          "text-muted-foreground size-3.5 shrink-0 transition-transform group-open/tool:rotate-90",
          !expandable && "invisible"
        )}
      />
      <ToolActivityIcon activity={activity} />
      <span className="min-w-0 truncate">
        <span className="text-foreground font-medium">
          {verbForActivity(activity)} {title}
        </span>
        {supportLabel && (
          <span className="text-muted-foreground ml-1.5 font-mono text-xs">{supportLabel}</span>
        )}
      </span>
      <StatusSuffix activity={activity} />
    </>
  )

  if (!expandable) {
    return (
      <div className={cn("text-muted-foreground flex min-w-0 items-center gap-2", textSize)}>
        {header}
      </div>
    )
  }

  return (
    <details className="group/tool min-w-0">
      <summary
        className={cn(
          "text-muted-foreground hover:text-foreground flex min-w-0 cursor-pointer list-none items-center gap-2",
          textSize
        )}
      >
        {header}
      </summary>
      <div className="mt-2 ml-5 flex flex-col gap-3">
        {hasArgs && <JsonBlock label="Arguments" value={activity.args} />}
        {hasResult && <JsonBlock label="Result" value={activity.result} />}
      </div>
    </details>
  )
}

function JsonBlock({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="min-w-0">
      <p className="text-muted-foreground mb-1 text-xs font-medium">{label}</p>
      <pre className="bg-muted/50 max-h-64 overflow-auto rounded-md p-2 text-xs leading-relaxed whitespace-pre-wrap">
        {safeJsonPreview(value)}
      </pre>
    </div>
  )
}

function StatusSuffix({ activity }: { activity: ToolActivity }) {
  const suffix = statusSuffix(activity)
  if (!suffix) {
    return null
  }

  return (
    <span
      className={cn(
        "shrink-0 text-xs",
        activity.status === "failed" || activity.status === "denied"
          ? "text-destructive"
          : "text-muted-foreground"
      )}
    >
      {suffix}
    </span>
  )
}

function ToolActivityIcon({ activity }: { activity: ToolActivity }) {
  if (activity.status === "awaiting_approval") {
    return <ShieldAlertIcon className="text-muted-foreground size-3.5 shrink-0" />
  }
  if (activity.status === "failed" || activity.status === "denied") {
    return <TriangleAlertIcon className="text-destructive size-3.5 shrink-0" />
  }
  if (activity.status === "completed") {
    return <CheckCircle2Icon className="text-muted-foreground size-3.5 shrink-0" />
  }
  if (activity.status === "running") {
    return <CircleDashedIcon className="text-muted-foreground size-3.5 shrink-0 animate-spin" />
  }
  return <WrenchIcon className="text-muted-foreground size-3.5 shrink-0" />
}

function verbForActivity(activity: ToolActivity) {
  if (activity.status === "running") {
    return "Running"
  }
  if (activity.status === "awaiting_approval") {
    return "Requested"
  }
  return "Ran"
}

function statusSuffix(activity: ToolActivity) {
  if (activity.status === "awaiting_approval") {
    return "· waiting"
  }
  if (activity.status === "failed") {
    return "· failed"
  }
  if (activity.status === "denied") {
    return "· denied"
  }
  return null
}
