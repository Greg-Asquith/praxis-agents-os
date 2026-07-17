// apps/web/src/features/conversations/components/tool-approval-card.tsx

import type { ReactNode } from "react"
import { CheckIcon, WrenchIcon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { ToolUiIcon } from "@/features/conversations/components/tool-ui-icon"
import type { LocalApprovalDecision } from "@/features/conversations/approval-decisions"
import { cn } from "@/lib/utils"

export function ToolApprovalCard({
  children,
  decision,
  footer,
  iconToken,
  prompt,
  title,
}: {
  children: ReactNode
  decision: LocalApprovalDecision["decision"]
  footer: ReactNode
  iconToken: string | null
  prompt?: string
  title: string
}) {
  const awaitingDecision = decision === "pending"

  return (
    <section
      aria-label={`Approval request: ${title}`}
      className={cn(
        "bg-card w-full max-w-3xl min-w-0 overflow-hidden rounded-lg border shadow-xs",
        awaitingDecision && "border-warning/40"
      )}
    >
      <div className="flex min-w-0 items-start gap-3 px-4 pt-4">
        <div className="bg-muted text-muted-foreground mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg">
          {iconToken && iconToken !== "tool" ? (
            <ToolUiIcon token={iconToken} />
          ) : (
            <WrenchIcon className="size-4" />
          )}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <h3 className="text-foreground text-sm font-medium">{title}</h3>
            {awaitingDecision ? (
              <Badge variant="warning">Requires Approval</Badge>
            ) : decision === "approved" ? (
              <span className="text-success inline-flex items-center gap-1 text-xs font-medium">
                Approved <CheckIcon className="size-3.5" />
              </span>
            ) : (
              <span className="text-muted-foreground text-xs font-medium">Declined</span>
            )}
          </div>
          {awaitingDecision && prompt ? (
            <p className="text-muted-foreground mt-1 text-sm leading-relaxed">{prompt}</p>
          ) : null}
        </div>
      </div>
      <div className="flex min-w-0 flex-col gap-3 px-4 py-4">{children}</div>
      <div className="border-border/60 flex min-w-0 flex-col gap-2 border-t px-4 py-3">
        {footer}
      </div>
    </section>
  )
}
