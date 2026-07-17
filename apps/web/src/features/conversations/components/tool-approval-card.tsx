// apps/web/src/features/conversations/components/tool-approval-card.tsx

import type { ReactNode } from "react"
import { CheckIcon, WrenchIcon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { ToolUiIcon } from "@/features/conversations/components/tool-ui-icon"
import { ToolSurfaceCard } from "@/features/conversations/components/tool-surface-card"
import type { LocalApprovalDecision } from "@/features/conversations/approval-decisions"

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
    <ToolSurfaceCard
      accent={awaitingDecision}
      ariaLabel={`Approval request: ${title}`}
      footer={footer}
      header={
        <>
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
        </>
      }
      icon={
        iconToken && iconToken !== "tool" ? (
          <ToolUiIcon token={iconToken} />
        ) : (
          <WrenchIcon className="size-4" />
        )
      }
    >
      {children}
    </ToolSurfaceCard>
  )
}
