// apps/web/src/features/home/components/agent-launcher.tsx

import { Link } from "@tanstack/react-router"
import { ArrowRightIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { useAgentsQuery } from "@/features/agents/api/list-agents"
import { AgentIdentityIcon } from "@/features/agents/components/agent-identity-icon"
import type { Agent } from "@/features/agents/types"
import { HomeSection } from "@/features/home/components/home-section"

const AGENT_LIMIT = 8

function compareByLastUsed(left: Agent, right: Agent): number {
  return lastUsedTimestamp(right.last_used_at) - lastUsedTimestamp(left.last_used_at)
}

function lastUsedTimestamp(lastUsedAt: string | null): number {
  if (lastUsedAt === null) {
    return 0
  }

  const timestamp = Date.parse(lastUsedAt)
  return Number.isNaN(timestamp) ? 0 : timestamp
}

export function AgentLauncher() {
  const { data } = useAgentsQuery({ includeInactive: false, limit: 100 })
  const agents = data.agents
    .filter((agent) => agent.is_active)
    .toSorted(compareByLastUsed)
    .slice(0, AGENT_LIMIT)

  if (agents.length === 0) {
    return null
  }

  return (
    <HomeSection
      action={
        <Button size="sm" variant="ghost" render={<Link to="/agents" />}>
          All Agents
        </Button>
      }
      description="Choose an agent and tell it what you need."
      title="Start with an Agent"
    >
      <div className="grid gap-1 sm:grid-cols-2 xl:grid-cols-4">
        {agents.map((agent) => (
          <Link
            className="hover:bg-muted focus-visible:ring-ring group flex min-w-0 items-center gap-3 rounded-lg px-3 py-3 transition-colors focus-visible:ring-2 focus-visible:outline-none"
            key={agent.id}
            search={{ agent: agent.id }}
            to="/conversations/new"
          >
            <AgentIdentityIcon
              agentId={agent.id}
              decorative
              metadata={agent.metadata}
              name={agent.name}
              size="md"
            />
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm font-medium">{agent.name}</span>
              <span className="text-muted-foreground line-clamp-1 text-xs">
                {agent.description ?? "Ready for a new conversation"}
              </span>
            </span>
            <ArrowRightIcon
              aria-hidden="true"
              className="text-muted-foreground size-3.5 shrink-0 transition-transform group-hover:translate-x-0.5"
            />
          </Link>
        ))}
      </div>
    </HomeSection>
  )
}
