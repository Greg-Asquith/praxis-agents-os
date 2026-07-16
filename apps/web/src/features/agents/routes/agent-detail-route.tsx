// apps/web/src/features/agents/routes/agent-detail-route.tsx

import { useState } from "react"
import { useNavigate, useParams } from "@tanstack/react-router"
import { Trash2Icon } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { useDeleteAgentMutation } from "@/features/agents/api/delete-agent"
import { useAgentQuery } from "@/features/agents/api/get-agent"
import { useAgentsQuery } from "@/features/agents/api/list-agents"
import { useUpdateAgentMutation } from "@/features/agents/api/update-agent"
import { AgentForm } from "@/features/agents/components/agent-form"
import { AgentIdentityIcon } from "@/features/agents/components/agent-identity-icon"
import type { AgentUpdateRequest } from "@/features/agents/types"
import { useModelCatalogQuery } from "@/features/models/api/list-model-catalog"
import { getErrorMessage } from "@/lib/api/errors"

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
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)

  async function handleUpdateAgent(payload: AgentUpdateRequest) {
    setDeleteError(null)
    await updateAgentMutation.mutateAsync({ agentId: agent.id, payload })
    await navigate({ to: "/agents" })
  }

  async function handleDeleteAgent() {
    setDeleteError(null)

    try {
      await deleteAgentMutation.mutateAsync(agent.id)
      await navigate({ to: "/agents" })
    } catch (mutationError) {
      setDeleteError(getErrorMessage(mutationError))
      setDeleteDialogOpen(false)
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col justify-between gap-4 md:flex-row md:items-start">
        <div className="flex min-w-0 items-start gap-3">
          <AgentIdentityIcon agentId={agent.id} decorative name={agent.name} size="lg" />
          <div className="flex min-w-0 flex-col gap-2">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="font-heading text-2xl font-semibold tracking-normal">{agent.name}</h1>
              {agent.is_favorite ? <Badge variant="secondary">Favorite</Badge> : null}
              {!agent.is_active ? <Badge variant="outline">Inactive</Badge> : null}
            </div>
            <p className="text-muted-foreground max-w-3xl text-sm">
              {agent.description ?? "No description has been set for this agent."}
            </p>
          </div>
        </div>
        <Button
          disabled={deleteAgentMutation.isPending}
          onClick={() => {
            setDeleteDialogOpen(true)
          }}
          variant="destructive"
        >
          <Trash2Icon data-icon="inline-start" />
          {deleteAgentMutation.isPending ? "Deleting" : "Delete Agent"}
        </Button>
        <ConfirmDialog
          confirmIcon={<Trash2Icon data-icon="inline-start" />}
          confirmLabel="Delete Agent"
          confirmPendingLabel="Deleting"
          description={`This removes ${agent.name} from the workspace. Existing conversations remain in their history.`}
          isPending={deleteAgentMutation.isPending}
          onConfirm={handleDeleteAgent}
          onOpenChange={setDeleteDialogOpen}
          open={deleteDialogOpen}
          title="Delete Agent?"
        />
      </div>

      {deleteError && (
        <Alert variant="destructive">
          <AlertTitle>Agent not deleted</AlertTitle>
          <AlertDescription>{deleteError}</AlertDescription>
        </Alert>
      )}

      <div className="mx-auto w-full max-w-5xl">
        <AgentForm
          key={`${agent.id}:${agent.updated_at}`}
          agent={agent}
          agents={agentsData.agents}
          cancelLabel="Back to Agents"
          isSubmitting={updateAgentMutation.isPending}
          mode="edit"
          modelCatalog={modelCatalog}
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
