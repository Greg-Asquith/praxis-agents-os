// apps/web/src/features/conversations/routes/new-conversation-route.tsx

import { CircleDashedIcon, MessageSquarePlusIcon } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import { useAgentsQuery } from "@/features/agents/api/list-agents"
import { ConversationComposer } from "@/features/conversations/components/conversation-composer"
import { useConversationWorkspace } from "@/features/conversations/conversation-workspace-context"

export function NewConversationRoute() {
  const { data: agentsData } = useAgentsQuery({ includeInactive: false, limit: 100 })
  const { stream } = useConversationWorkspace()
  const activeAgentCount = agentsData.agents.filter((agent) => agent.is_active).length

  return (
    <div className="bg-background flex h-full min-h-0 min-w-0 flex-col overflow-hidden">
      <header className="shrink-0">
        <div className="mx-auto flex w-full max-w-5xl flex-col justify-between gap-3 px-4 py-4 md:flex-row md:items-start">
          <div className="min-w-0">
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <Badge variant="outline">Direct</Badge>
              {stream.isStreaming && (
                <Badge variant="secondary">
                  <CircleDashedIcon className="animate-spin" data-icon="inline-start" />
                  Starting
                </Badge>
              )}
            </div>
            <h1 className="font-heading text-xl font-semibold">New Conversation</h1>
            <p className="text-muted-foreground mt-1 text-sm">
              {activeAgentCount} active {activeAgentCount === 1 ? "agent" : "agents"} available.
            </p>
          </div>
        </div>
      </header>

      <Separator />

      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto min-h-full w-full max-w-5xl px-4 py-4">
          <div className="flex min-h-full flex-col items-center justify-center text-center">
            {activeAgentCount === 0 ? (
              <Alert className="max-w-lg text-left">
                <MessageSquarePlusIcon />
                <AlertTitle>No active agents</AlertTitle>
                <AlertDescription>
                  Activate an agent before starting a workspace conversation.
                </AlertDescription>
              </Alert>
            ) : (
              <>
                <div className="bg-muted text-muted-foreground mb-4 flex size-11 items-center justify-center rounded-full">
                  <MessageSquarePlusIcon className="size-5" />
                </div>
                <h2 className="font-heading text-lg font-medium">Blank chat</h2>
                <p className="text-muted-foreground mt-2 max-w-sm text-sm">
                  Choose an agent below and send the first prompt.
                </p>
              </>
            )}
          </div>
        </div>
      </div>

      <Separator />
      <footer className="shrink-0">
        <div className="mx-auto w-full max-w-5xl px-4 py-3">
          <ConversationComposer mode="create" agents={agentsData.agents} />
        </div>
      </footer>
    </div>
  )
}
