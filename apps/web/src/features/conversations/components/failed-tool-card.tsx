// apps/web/src/features/conversations/components/failed-tool-card.tsx


import { ChevronRightIcon, RotateCcwIcon, TriangleAlertIcon } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { ActivityStatusBadge } from "@/features/conversations/components/tool-activity-status"
import { ToolFieldGrid } from "@/features/conversations/components/tool-field"
import { ToolSurfaceCard } from "@/features/conversations/components/tool-surface-card"
import { ToolUiIcon } from "@/features/conversations/components/tool-ui-icon"
import type { ToolActivity } from "@/features/conversations/message-parts"
import { friendlyResultText, type ResolvedToolField } from "@/features/conversations/tool-ui"

export function FailedToolCard({
  activity,
  argFields,
  headline,
  iconToken,
}: {
  activity: ToolActivity
  argFields: ResolvedToolField[]
  headline: string
  iconToken: string | null
}) {
  const message =
    friendlyResultText(activity.result) ??
    friendlyResultText(activity.resultExcerpt) ??
    "This attempt did not complete. No further error details were recorded."
  const canAdjust = activity.kind === "retry" || activity.outcome === "retry"

  return (
    <ToolSurfaceCard
      ariaLabel={headline}
      header={
        <div className="flex min-w-0 items-start gap-2 pt-1">
          <h3 className="min-w-0 flex-1 text-sm font-medium wrap-break-word">{headline}</h3>
          <ActivityStatusBadge status="failed" />
        </div>
      }
      icon={<ToolUiIcon token={iconToken} />}
      footer={
        <div className="text-muted-foreground flex items-start gap-2 text-xs">
          {canAdjust ? <RotateCcwIcon className="mt-0.5 size-3.5 shrink-0" /> : null}
          <p>
            {canAdjust
              ? "The agent received this error and can adjust its next attempt."
              : "Any further attempts appear as separate steps in this conversation."}
          </p>
        </div>
      }
    >
      <Alert variant="destructive">
        <TriangleAlertIcon />
        <AlertTitle>What went wrong</AlertTitle>
        <AlertDescription className="max-h-60 min-w-0 overflow-y-auto wrap-anywhere whitespace-pre-wrap">
          {message}
        </AlertDescription>
      </Alert>
      {argFields.length > 0 ? (
        <details className="group/request min-w-0">
          <summary className="text-muted-foreground hover:text-foreground flex cursor-pointer list-none items-center gap-1.5 rounded-md py-1 text-xs">
            <ChevronRightIcon className="size-3.5 shrink-0 transition-transform group-open/request:rotate-90" />
            Request details
          </summary>
          <div className="pt-3">
            <ToolFieldGrid fields={argFields} />
          </div>
        </details>
      ) : null}
    </ToolSurfaceCard>
  )
}
