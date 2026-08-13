// apps/web/src/features/home/components/approvals-inbox.tsx

import { Link } from "@tanstack/react-router"
import { CheckIcon, Clock3Icon } from "lucide-react"

import { AgentIdentityIcon } from "@/features/agents/components/agent-identity-icon"
import { usePendingApprovalsQuery } from "@/features/conversations/api/list-pending-approvals"
import { HomeSection } from "@/features/home/components/home-section"
import { relativeDateTime, titleCaseToken } from "@/lib/format"

export function ApprovalsInbox() {
  const { data } = usePendingApprovalsQuery()
  const remaining = Math.max(0, data.total - data.items.length)

  return (
    <HomeSection
      description="Runs paused until you review their next action."
      title="Waiting for Approval"
    >
      {data.items.length === 0 ? (
        <div className="text-muted-foreground flex items-center gap-2 px-2 py-3 text-sm">
          <CheckIcon aria-hidden="true" className="text-success size-4" />
          Nothing waiting for approval
        </div>
      ) : (
        <div className="grid gap-1 lg:grid-cols-2">
          {data.items.map((item) => {
            const agentName = item.agent_name ?? "Agent"
            const toolNames = item.pending_tool_names
              .map((name) => titleCaseToken(name, "Tool"))
              .join(", ")
            const delegatedNames = item.delegated_agent_names.join(", ")

            return (
              <Link
                className="hover:bg-muted focus-visible:ring-ring flex min-w-0 items-center gap-3 rounded-lg px-3 py-2.5 transition-colors focus-visible:ring-2 focus-visible:outline-none"
                key={item.run_id}
                params={{ conversationId: item.conversation_id }}
                to="/conversations/$conversationId"
              >
                <AgentIdentityIcon
                  agentId={item.agent_id ?? item.run_id}
                  decorative
                  name={agentName}
                  size="md"
                />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium">
                    {item.conversation_title ?? "Untitled conversation"}
                  </span>
                  <span className="text-muted-foreground line-clamp-1 text-xs">
                    {agentName} wants to run {toolNames}
                    {delegatedNames ? ` via ${delegatedNames}` : null}
                  </span>
                </span>
                <span className="text-muted-foreground flex shrink-0 items-center gap-1 text-xs">
                  <Clock3Icon aria-hidden="true" className="size-3" />
                  {relativeDateTime(item.awaiting_since)}
                </span>
              </Link>
            )
          })}
          {remaining > 0 ? (
            <p className="text-muted-foreground px-3 pt-2 pb-1 text-xs lg:col-span-2">
              and {String(remaining)} more
            </p>
          ) : null}
        </div>
      )}
    </HomeSection>
  )
}
