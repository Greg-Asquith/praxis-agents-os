// apps/web/src/features/agents/routes/agents-route.tsx

import { Link } from "@tanstack/react-router"
import { BotIcon, PlusIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { useAgentsQuery } from "@/features/agents/api/list-agents"
import { countActiveAgents } from "@/features/agents/agent-metrics"
import { AgentsTable } from "@/features/agents/components/agents-table"
import { useModelCatalogQuery } from "@/features/models/api/list-model-catalog"
import { pluralize } from "@/lib/format"

export function AgentsRoute() {
  const { data: agentsData } = useAgentsQuery({ includeInactive: true, limit: 100 })
  const { data: modelCatalog } = useModelCatalogQuery()
  const activeAgents = countActiveAgents(agentsData.agents)
  const hasAgents = agentsData.agents.length > 0

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col justify-between gap-4 md:flex-row md:items-start">
        <div className="flex min-w-0 flex-col gap-2">
          <p className="text-muted-foreground text-sm font-medium">Agent runtime</p>
          <h1 className="font-heading text-2xl font-semibold tracking-normal">Agents</h1>
        </div>
        {hasAgents ? (
          <Button render={<Link to="/agents/new" />}>
            <PlusIcon data-icon="inline-start" />
            New agent
          </Button>
        ) : null}
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <Card size="sm">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <BotIcon className="size-4" />
              Total agents
            </CardTitle>
            <CardDescription>
              {agentsData.total} {pluralize(agentsData.total, "agent")} in this workspace
            </CardDescription>
          </CardHeader>
        </Card>
        <Card size="sm">
          <CardHeader>
            <CardTitle>Active</CardTitle>
            <CardDescription>
              {activeAgents} {pluralize(activeAgents, "agent")} available for runs
            </CardDescription>
          </CardHeader>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Workspace agents</CardTitle>
          <CardDescription>
            Configure active agents, model overrides, delegation, and tool approval policies.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <AgentsTable agents={agentsData.agents} modelCatalog={modelCatalog} />
        </CardContent>
      </Card>
    </div>
  )
}
