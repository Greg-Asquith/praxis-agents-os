// apps/web/src/features/agents/routes/agents-route.tsx

import { useState } from "react"
import { useNavigate } from "@tanstack/react-router"
import { BotIcon, PlusIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { useCreateAgentMutation } from "@/features/agents/api/create-agent"
import { useAgentsQuery } from "@/features/agents/api/list-agents"
import {
  countActiveAgents,
  countApprovalGatedAgents,
} from "@/features/agents/agent-metrics"
import { AgentForm } from "@/features/agents/components/agent-form"
import { AgentsTable } from "@/features/agents/components/agents-table"
import type { AgentCreateRequest } from "@/features/agents/types"
import { useModelCatalogQuery } from "@/features/models/api/list-model-catalog"
import { pluralize } from "@/lib/format"

export function AgentsRoute() {
  const navigate = useNavigate()
  const { data: agentsData } = useAgentsQuery({ includeInactive: true, limit: 100 })
  const { data: modelCatalog } = useModelCatalogQuery()
  const createAgentMutation = useCreateAgentMutation()
  const [createDialogOpen, setCreateDialogOpen] = useState(false)
  const activeAgents = countActiveAgents(agentsData.agents)
  const approvalGatedAgents = countApprovalGatedAgents(agentsData.agents)

  async function handleCreateAgent(payload: AgentCreateRequest) {
    const agent = await createAgentMutation.mutateAsync(payload)
    setCreateDialogOpen(false)
    await navigate({ to: "/agents/$agentId", params: { agentId: agent.id } })
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col justify-between gap-4 md:flex-row md:items-start">
        <div className="flex min-w-0 flex-col gap-2">
          <p className="text-muted-foreground text-sm font-medium">Agent runtime</p>
          <h1 className="font-heading text-2xl font-semibold tracking-normal">Agents</h1>
        </div>
        <Dialog open={createDialogOpen} onOpenChange={setCreateDialogOpen}>
          <DialogTrigger render={<Button />}>
            <PlusIcon data-icon="inline-start" />
            New agent
          </DialogTrigger>
          <DialogContent className="max-h-[calc(100vh-2rem)] overflow-y-auto sm:max-w-4xl">
            <DialogHeader>
              <DialogTitle>New agent</DialogTitle>
              <DialogDescription>
                Configure the model, tools, delegation boundary, and approval policy.
              </DialogDescription>
            </DialogHeader>
            <AgentForm
              agents={agentsData.agents}
              isSubmitting={createAgentMutation.isPending}
              mode="create"
              modelCatalog={modelCatalog}
              onSubmit={handleCreateAgent}
            />
          </DialogContent>
        </Dialog>
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
        <Card size="sm">
          <CardHeader>
            <CardTitle>Approval gated</CardTitle>
            <CardDescription>
              {approvalGatedAgents} {pluralize(approvalGatedAgents, "agent")} has human review
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
