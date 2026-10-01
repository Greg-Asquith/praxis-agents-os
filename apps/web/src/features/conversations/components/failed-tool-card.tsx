// apps/web/src/features/conversations/components/failed-tool-card.tsx

import { TriangleAlertIcon } from "lucide-react"
import type { ReactNode } from "react"

import { ToolResultCard } from "@/components/tool-ui/result-card"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { ActivityStatusBadge } from "@/features/conversations/components/tool-activity-status"
import { ToolUiIcon } from "@/features/conversations/components/tool-ui-icon"
import type { ToolActivity } from "@/features/conversations/message-parts"
import { friendlyResultText, type ResolvedToolField } from "@/features/conversations/tool-ui"

export function FailedToolCard({
  activity,
  argFields,
  children,
  defaultOpen = false,
  label,
  iconToken,
  message: messageOverride = null,
}: {
  activity: ToolActivity
  argFields: ResolvedToolField[]
  children?: ReactNode
  defaultOpen?: boolean
  label: string
  iconToken: string | null
  message?: string | null
}) {
  const stopped = activity.status === "stopped"
  const message =
    messageOverride ??
    friendlyResultText(activity.result) ??
    friendlyResultText(activity.resultExcerpt) ??
    (stopped
      ? "The run ended before a result was recorded for this call. Its outcome is unconfirmed."
      : "This attempt did not complete. No further error details were recorded.")
  const canAdjust = activity.kind === "retry" || activity.outcome === "retry"

  return (
    <ToolResultCard
      ariaLabel={`${label} ${stopped ? "stopped" : "failed"}`}
      defaultOpen={defaultOpen}
      details={argFields.map((field) => ({ label: field.label, value: field.value }))}
      heading={
        <span className="inline-flex min-w-0 items-center gap-2">
          <ToolUiIcon token={iconToken} />
          <span className="truncate">{label}</span>
        </span>
      }
      trailing={<ActivityStatusBadge status={stopped ? "stopped" : "failed"} />}
    >
      <div className="flex min-w-0 flex-col gap-3">
        <Alert variant={stopped ? "default" : "destructive"}>
          <TriangleAlertIcon />
          <AlertTitle>{stopped ? "Why This Call Stopped" : "What Went Wrong"}</AlertTitle>
          <AlertDescription className="wrap-anywhere whitespace-pre-wrap">
            {message}
          </AlertDescription>
        </Alert>
        {canAdjust ? (
          <p className="text-muted-foreground text-xs">
            The agent received this error and can adjust its next attempt.
          </p>
        ) : null}
        {children}
      </div>
    </ToolResultCard>
  )
}
