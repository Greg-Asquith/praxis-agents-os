// apps/web/src/features/home/components/schedule-attention.tsx

import { Link } from "@tanstack/react-router"
import { MessageSquareTextIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { useAgentsQuery } from "@/features/agents/api/list-agents"
import { HomeSection } from "@/features/home/components/home-section"
import { useSchedulesQuery } from "@/features/schedules/api/list-schedules"
import { ScheduleHealthBadge } from "@/features/schedules/components/schedule-status-badges"
import { scheduleTitle } from "@/features/schedules/format"
import { truncateText } from "@/lib/format"

export function ScheduleAttention() {
  const { data: schedulesData } = useSchedulesQuery({ includeInactive: true, limit: 100 })
  const { data: agentsData } = useAgentsQuery({ includeInactive: true, limit: 100 })
  const schedules = schedulesData.items.filter(
    (schedule) => schedule.health === "needs_attention" || schedule.health === "retrying"
  )

  if (schedules.length === 0) {
    return null
  }

  const agentNames = new Map(agentsData.agents.map((agent) => [agent.id, agent.name]))

  return (
    <HomeSection
      action={
        <Button size="sm" variant="ghost" render={<Link to="/schedules" />}>
          View Schedules
        </Button>
      }
      description="Automated work that is failing or retrying."
      title="Schedules Needing Attention"
    >
      <div className="flex flex-col gap-1">
        {schedules.map((schedule) => (
          <div
            className="hover:bg-muted flex min-w-0 flex-col gap-2 rounded-lg px-3 py-2.5 transition-colors sm:flex-row sm:items-center sm:justify-between"
            key={schedule.id}
          >
            <div className="min-w-0">
              <Link
                className="focus-visible:ring-ring rounded-sm text-sm font-medium hover:underline focus-visible:ring-2 focus-visible:outline-none"
                params={{ scheduleId: schedule.id }}
                to="/schedules/$scheduleId"
              >
                {scheduleTitle(schedule)}
              </Link>
              <p className="text-muted-foreground mt-0.5 truncate text-xs">
                {agentNames.get(schedule.agent_id) ?? "Unknown agent"}
                {schedule.default_prompt ? ` · ${truncateText(schedule.default_prompt, 80)}` : ""}
              </p>
              {schedule.latest_run?.last_error_message ? (
                <p className="text-destructive mt-1 line-clamp-1 text-xs">
                  {truncateText(schedule.latest_run.last_error_message, 120)}
                </p>
              ) : null}
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <ScheduleHealthBadge health={schedule.health} />
              {schedule.latest_run?.conversation_id ? (
                <Button
                  aria-label={`Open latest run for ${scheduleTitle(schedule)}`}
                  size="icon-sm"
                  variant="ghost"
                  render={
                    <Link
                      params={{ conversationId: schedule.latest_run.conversation_id }}
                      to="/conversations/$conversationId"
                    />
                  }
                >
                  <MessageSquareTextIcon />
                </Button>
              ) : null}
            </div>
          </div>
        ))}
      </div>
    </HomeSection>
  )
}
