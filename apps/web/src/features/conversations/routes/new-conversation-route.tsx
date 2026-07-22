// apps/web/src/features/conversations/routes/new-conversation-route.tsx

import { CircleDashedIcon, MessageSquarePlusIcon } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { useAgentsQuery } from "@/features/agents/api/list-agents"
import { AgentIdentityIcon } from "@/features/agents/components/agent-identity-icon"
import { ConversationComposer } from "@/features/conversations/components/conversation-composer"
import { useConversationWorkspace } from "@/features/conversations/conversation-workspace-context"
import { useModelCatalogQuery } from "@/features/models/api/list-model-catalog"

const MAX_AGENT_ICONS = 5

export function NewConversationRoute() {
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
            <Alert className="max-w-lg text-left">
              <MessageSquarePlusIcon />
              <AlertTitle>No active agents</AlertTitle>
              <AlertDescription>
                Activate an agent before starting a workspace conversation.
              </AlertDescription>
            </Alert>
          ) : stream.isStreaming ? (
            <div className="text-muted-foreground flex items-center gap-2 text-sm">
              <CircleDashedIcon aria-hidden="true" className="size-4 animate-spin" />
              Starting your conversation
            </div>
          ) : (
            <>
              <div aria-hidden="true" className="mb-5 flex items-center">
                {shownAgents.map((agent) => (
                  <span
                    className="ring-background rounded-lg ring-2 not-first:-ml-2"
                    key={agent.id}
                  >
                    <AgentIdentityIcon agentId={agent.id} decorative name={agent.name} size="lg" />
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

      <footer className="shrink-0">
        <div className="mx-auto w-full max-w-4xl px-4 pt-2 pb-4">
          <ConversationComposer
            mode="create"
            agents={agentsData.agents}
            modelCatalog={modelCatalog}
          />
        </div>
      </footer>
    </div>
  )
}
