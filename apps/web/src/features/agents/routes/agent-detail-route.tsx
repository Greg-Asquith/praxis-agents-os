// apps/web/src/features/agents/routes/agent-detail-route.tsx

import { useState } from "react"
import { Link, useNavigate, useParams } from "@tanstack/react-router"
import {
  ArrowLeftIcon,
  BotIcon,
  ClockIcon,
  NetworkIcon,
  Trash2Icon,
  WrenchIcon,
} from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { MetricCard } from "@/components/ui/metric-card"
import { useDeleteAgentMutation } from "@/features/agents/api/delete-agent"
import { useAgentQuery } from "@/features/agents/api/get-agent"
import { useAgentsQuery } from "@/features/agents/api/list-agents"
import { useUpdateAgentMutation } from "@/features/agents/api/update-agent"
import { AgentForm } from "@/features/agents/components/agent-form"
import { AgentStatusBadges } from "@/features/agents/components/agent-status-badges"
import { formatAgentModel } from "@/features/agents/components/agent-model-label"
import type { AgentUpdateRequest } from "@/features/agents/types"
import { useModelCatalogQuery } from "@/features/models/api/list-model-catalog"
import { getErrorMessage } from "@/lib/api/errors"
import { formatDateTime, pluralize } from "@/lib/format"

export function AgentDetailRoute() {
  const navigate = useNavigate()
  const params = useParams({ strict: false })
  const agentId = requireAgentId(params.agentId)
  const { data: agent } = useAgentQuery(agentId)
  const { data: agentsData } = useAgentsQuery({ includeInactive: true, limit: 100 })
  const { data: modelCatalog } = useModelCatalogQuery()
  const updateAgentMutation = useUpdateAgentMutation()
  const deleteAgentMutation = useDeleteAgentMutation()
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  async function handleUpdateAgent(payload: AgentUpdateRequest) {
    setDeleteError(null)
    setSaved(false)
    await updateAgentMutation.mutateAsync({ agentId: agent.id, payload })
    setSaved(true)
  }

  async function handleDeleteAgent() {
    setDeleteError(null)
    setSaved(false)

    if (!window.confirm(`Delete ${agent.name}?`)) {
      return
    }

    try {
      await deleteAgentMutation.mutateAsync(agent.id)
      await navigate({ to: "/agents" })
    } catch (mutationError) {
      setDeleteError(getErrorMessage(mutationError))
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col justify-between gap-4 md:flex-row md:items-start">
        <div className="flex min-w-0 flex-col gap-3">
          <Button className="w-fit" size="sm" variant="outline" render={<Link to="/agents" />}>
            <ArrowLeftIcon data-icon="inline-start" />
            Agents
          </Button>
          <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center gap-2">
              <AgentStatusBadges agent={agent} />
              <Badge variant="outline">{agent.slug}</Badge>
            </div>
            <h1 className="font-heading text-2xl font-semibold tracking-normal">{agent.name}</h1>
            <p className="text-muted-foreground max-w-3xl text-sm">
              {agent.description ?? "No description has been set for this agent."}
            </p>
          </div>
        </div>
        <Button
          disabled={deleteAgentMutation.isPending}
          onClick={() => {
            void handleDeleteAgent()
          }}
          variant="destructive"
        >
          <Trash2Icon data-icon="inline-start" />
          {deleteAgentMutation.isPending ? "Deleting" : "Delete agent"}
        </Button>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          description={formatAgentModel(agent, modelCatalog)}
          icon={<BotIcon className="size-4" />}
          title="Model"
        />
        <MetricCard
          description={`${String(agent.tool_names.length)} ${pluralize(
            agent.tool_names.length,
            "tool"
          )} configured`}
          icon={<WrenchIcon className="size-4" />}
          title="Tools"
        />
        <MetricCard
          description={`${String(agent.allowed_agent_ids.length)} ${pluralize(
            agent.allowed_agent_ids.length,
            "sub-agent"
          )} allowed`}
          icon={<NetworkIcon className="size-4" />}
          title="Delegation"
        />
        <MetricCard
          description={formatDateTime(agent.last_used_at)}
          icon={<ClockIcon className="size-4" />}
          title="Last used"
        />
      </div>

      {deleteError && (
        <Alert variant="destructive">
          <AlertTitle>Agent not deleted</AlertTitle>
          <AlertDescription>{deleteError}</AlertDescription>
        </Alert>
      )}
      {saved && (
        <Alert>
          <AlertTitle>Agent updated</AlertTitle>
          <AlertDescription>Your changes have been saved.</AlertDescription>
        </Alert>
      )}

      <div className="mx-auto w-full max-w-5xl">
        <AgentForm
          key={`${agent.id}:${agent.updated_at}`}
          agent={agent}
          agents={agentsData.agents}
          cancelLabel="Back to agents"
          cancelTo="/agents"
          isSubmitting={updateAgentMutation.isPending}
          mode="edit"
          modelCatalog={modelCatalog}
          onChange={() => {
            if (saved) {
              setSaved(false)
            }
          }}
          onSubmit={handleUpdateAgent}
        />
      </div>
    </div>
  )
}

function requireAgentId(value: string | undefined) {
  if (!value) {
    throw new Error("Agent route is missing an agent id.")
  }

  return value
}
