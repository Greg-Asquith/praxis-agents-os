// apps/web/src/features/home/components/approvals-inbox.tsx

import { Link } from "@tanstack/react-router"
import { CheckIcon, Clock3Icon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
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
        <div className="flex flex-col gap-1">
          {data.items.map((item) => (
            <Link
              className="hover:bg-muted focus-visible:ring-ring flex min-w-0 flex-col gap-2 rounded-lg px-3 py-2.5 transition-colors focus-visible:ring-2 focus-visible:outline-none sm:flex-row sm:items-center sm:justify-between"
              key={item.run_id}
              params={{ conversationId: item.conversation_id }}
              to="/conversations/$conversationId"
            >
              <div className="min-w-0">
                <p className="truncate text-sm font-medium">
                  {item.pending_tool_names.map((name, index) => (
                    <Badge
                      className="mr-2 rounded-md"
                      key={`${name}-${String(index)}`}
                      variant="outline"
                    >
                      {titleCaseToken(name, "Tool")}
                    </Badge>
                  ))}
                  {item.agent_name ?? "Agent"}{" "}
                  <span className="text-muted-foreground font-normal">
                    in {item.conversation_title ?? "Untitled conversation"}
                  </span>
                  {item.delegated_agent_names.map((name, index) => (
                    <Badge
                      className="ml-2 rounded-md"
                      key={`${name}-${String(index)}`}
                      variant="outline"
                    >
                      via {name}
                    </Badge>
                  ))}
                </p>
              </div>
              <span className="text-muted-foreground flex shrink-0 items-center gap-1 text-xs">
                <Clock3Icon aria-hidden="true" className="size-3" />
                {relativeDateTime(item.awaiting_since)}
              </span>
            </Link>
          ))}
          {remaining > 0 ? (
            <p className="text-muted-foreground px-3 pt-2 pb-1 text-xs">
              and {String(remaining)} more
            </p>
          ) : null}
        </div>
      )}
    </HomeSection>
  )
}
