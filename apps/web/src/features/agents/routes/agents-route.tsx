// apps/web/src/features/agents/routes/agents-route.tsx

import { Link } from "@tanstack/react-router"
import { PlusIcon } from "lucide-react"

import { PageHeader } from "@/components/shell/page-header"
import { Button } from "@/components/ui/button"
import { useAgentsQuery } from "@/features/agents/api/list-agents"
import { AgentsTable } from "@/features/agents/components/agents-table"
import { useModelCatalogQuery } from "@/features/models/api/list-model-catalog"

export function AgentsRoute() {
  const { data: agentsData } = useAgentsQuery({ includeInactive: true, limit: 100 })
  const { data: modelCatalog } = useModelCatalogQuery()
  const hasAgents = agentsData.agents.length > 0

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        actions={
          hasAgents ? (
            <Button render={<Link to="/agents/new" />}>
              <PlusIcon data-icon="inline-start" />
              New Agent
            </Button>
          ) : null
        }
        description="Configure agents, models, tools, delegation, and approval policies."
        title="Agents"
      />

      <AgentsTable agents={agentsData.agents} modelCatalog={modelCatalog} />
    </div>
  )
}
