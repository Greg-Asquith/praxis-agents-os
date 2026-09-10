// apps/web/src/features/conversations/routes/new-conversation-route.tsx

import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { useRouterState } from "@tanstack/react-router"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import type { Agent } from "@/features/agents/types"
import type { ModelCatalogResponse } from "@/features/models/types"
import type { WorkspaceFile } from "@/features/files/types"
import { fileQueryOptions } from "@/features/files/api/get-file"
import { canAttachFile } from "@/features/files/chat-attachment"
import { attachmentFromWorkspaceFile } from "@/features/conversations/attachments"

import { useAgentsQuery } from "@/features/agents/api/list-agents"
import { AgentIdentityIcon } from "@/features/agents/components/agent-identity-icon"
import { ConversationComposer } from "@/features/conversations/components/conversation-composer"
import {
  ConversationStartingNotice,
  NoActiveAgentsAlert,
} from "@/features/conversations/components/conversation-starting-notice"
import { useConversationWorkspace } from "@/features/conversations/conversation-workspace-context"
import { useModelCatalogQuery } from "@/features/models/api/list-model-catalog"

const MAX_AGENT_ICONS = 5

export function NewConversationRoute() {
  const search = useRouterState({
    select: (state): { agent?: string; file?: string } => state.location.search,
  })
  const { data: agentsData } = useAgentsQuery({ includeInactive: false, limit: 100 })
  const { data: modelCatalog } = useModelCatalogQuery()
  const { stream } = useConversationWorkspace()
  const activeAgents = agentsData.agents.filter((agent) => agent.is_active)
  const shownAgents = activeAgents.slice(0, MAX_AGENT_ICONS)
  const hiddenAgentCount = activeAgents.length - shownAgents.length

  return (
    <div className="bg-background flex h-full min-h-0 min-w-0 flex-col overflow-hidden">
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto flex min-h-full w-full max-w-4xl flex-col items-center justify-center px-4 py-8 text-center">
          {activeAgents.length === 0 ? (
            <NoActiveAgentsAlert />
          ) : stream.isStreaming ? (
            <ConversationStartingNotice />
          ) : (
            <>
              <div aria-hidden="true" className="mb-5 flex items-center">
                {shownAgents.map((agent) => (
                  <span
                    className="ring-background rounded-lg ring-2 not-first:-ml-2"
                    key={agent.id}
                  >
                    <AgentIdentityIcon
                      agentId={agent.id}
                      decorative
                      metadata={agent.metadata}
                      name={agent.name}
                      size="lg"
                    />
                  </span>
                ))}
                {hiddenAgentCount > 0 ? (
                  <span className="bg-muted text-muted-foreground ring-background -ml-2 flex size-8 items-center justify-center rounded-lg text-xs font-medium ring-2">
                    +{hiddenAgentCount}
                  </span>
                ) : null}
              </div>
              <h1 className="font-heading text-xl font-medium tracking-tight">
                Start a new conversation
              </h1>
              <p className="text-muted-foreground mt-2 max-w-sm text-sm">
                {activeAgents.length === 1
                  ? `${activeAgents[0]?.name ?? "Your agent"} is ready to help.`
                  : `${String(activeAgents.length)} agents are ready to help.`}{" "}
                Choose one below and describe what you need.
              </p>
            </>
          )}
        </div>
      </div>

      {activeAgents.length > 0 ? (
        <footer className="shrink-0">
          <div className="mx-auto w-full max-w-4xl px-4 pt-2 pb-4">
            <NewConversationComposer
              key={search.file ?? "new"}
              fileId={search.file}
              initialAgentId={search.agent}
              agents={agentsData.agents}
              modelCatalog={modelCatalog}
            />
          </div>
        </footer>
      ) : null}
    </div>
  )
}

function NewConversationComposer({
  fileId,
  initialAgentId,
  agents,
  modelCatalog,
}: {
  fileId: string | undefined
  initialAgentId: string | undefined
  agents: Agent[]
  modelCatalog: ModelCatalogResponse
}) {
  const [initialFile, setInitialFile] = useState<WorkspaceFile | null>(null)
  const attachment = useQuery({
    ...fileQueryOptions(fileId ?? ""),
    enabled: Boolean(fileId) && initialFile === null,
    staleTime: 0,
    retry: false,
  })

  if (fileId && !initialFile) {
    if (attachment.isPending || !attachment.isFetchedAfterMount) {
      return (
        <p role="status" className="text-muted-foreground text-sm">
          Loading attachment…
        </p>
      )
    }
    if (attachment.isError || !canAttachFile(attachment.data)) {
      return (
        <Alert variant="destructive">
          <AlertTitle>File cannot be attached</AlertTitle>
          <AlertDescription>
            Return to Files and choose an available document or image.
          </AlertDescription>
        </Alert>
      )
    }
    // Once handed to the composer, its draft owns attachment removal and retry.
    setInitialFile(attachment.data)
    return null
  }

  return (
    <ConversationComposer
      mode="create"
      agents={agents}
      {...(initialAgentId ? { initialAgentId } : {})}
      {...(initialFile ? { initialAttachment: attachmentFromWorkspaceFile(initialFile) } : {})}
      modelCatalog={modelCatalog}
    />
  )
}
