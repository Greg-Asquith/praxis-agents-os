// apps/web/src/features/agents/routes/new-agent-route.tsx

import { Link, useNavigate } from "@tanstack/react-router"
import { ArrowLeftIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { useCreateAgentMutation } from "@/features/agents/api/create-agent"
import { useAgentsQuery } from "@/features/agents/api/list-agents"
import { AgentForm } from "@/features/agents/components/agent-form"
import type { AgentCreateRequest } from "@/features/agents/types"
import { useModelCatalogQuery } from "@/features/models/api/list-model-catalog"

export function NewAgentRoute() {
  const navigate = useNavigate()
  const { data: agentsData } = useAgentsQuery({ includeInactive: true, limit: 100 })
  const { data: modelCatalog } = useModelCatalogQuery()
  const createAgentMutation = useCreateAgentMutation()

  async function handleCreateAgent(payload: AgentCreateRequest) {
    const agent = await createAgentMutation.mutateAsync(payload)
    await navigate({ to: "/agents/$agentId", params: { agentId: agent.id } })
  }

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
      <div className="flex flex-col gap-3">
        <Button className="w-fit" size="sm" variant="outline" render={<Link to="/agents" />}>
          <ArrowLeftIcon data-icon="inline-start" />
          Agents
        </Button>
        <div className="flex flex-col gap-2">
          <p className="text-muted-foreground text-sm font-medium">Agent runtime</p>
          <h1 className="font-heading text-2xl font-semibold tracking-normal">New agent</h1>
          <p className="text-muted-foreground max-w-3xl text-sm">
            Define the agent identity, model, runtime limits, tools, and delegation boundary.
          </p>
        </div>
      </div>

      <AgentForm
        agents={agentsData.agents}
        cancelLabel="Cancel"
        cancelTo="/agents"
        isSubmitting={createAgentMutation.isPending}
        mode="create"
        modelCatalog={modelCatalog}
        onSubmit={handleCreateAgent}
      />
    </div>
  )
}
