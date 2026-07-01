// apps/web/src/features/conversations/routes/conversations-route.tsx

import { useCallback, useMemo, useState } from "react"
import { Link, Outlet, useNavigate, useParams } from "@tanstack/react-router"
import { MessageSquarePlusIcon, PlusIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Separator } from "@/components/ui/separator"
import { ConversationComposer } from "@/features/conversations/components/conversation-composer"
import { ConversationList } from "@/features/conversations/components/conversation-list"
import {
  ConversationWorkspaceContext,
  type ConversationWorkspaceContextValue,
} from "@/features/conversations/conversation-workspace-context"
import { useConversationsQuery } from "@/features/conversations/api/list-conversations"
import { useAgentsQuery } from "@/features/agents/api/list-agents"
import type { Agent } from "@/features/agents/types"
import type { ConversationMessage } from "@/features/conversations/types"
import type { PendingUserMessage } from "@/features/conversations/message-parts"
import { useAgentStream } from "@/features/conversations/stream/use-agent-stream"
import { pluralize } from "@/lib/format"

export function ConversationsRoute() {
  const { data: conversationsData } = useConversationsQuery({ limit: 100 })
  const { data: agentsData } = useAgentsQuery({ includeInactive: false, limit: 100 })
  const navigate = useNavigate()
  const params = useParams({ strict: false })
  const selectedConversationId = params.conversationId ?? null
  const [pendingUserMessages, setPendingUserMessages] = useState<PendingUserMessage[]>([])
  const [newConversationDialogOpen, setNewConversationDialogOpen] = useState(false)
  const conversations = useMemo(
    () => sortConversations(conversationsData.conversations),
    [conversationsData.conversations]
  )

  const addPendingUserMessage = useCallback((message: PendingUserMessage) => {
    setPendingUserMessages((current) => [...current, message])
  }, [])

  const removePendingUserMessage = useCallback((clientMessageId: string) => {
    setPendingUserMessages((current) =>
      current.filter((message) => message.clientMessageId !== clientMessageId)
    )
  }, [])

  const clearPersistedPendingMessages = useCallback((messages: ConversationMessage[]) => {
    const persistedClientIds = new Set(
      messages
        .map((message) => message.client_message_id)
        .filter((value): value is string => typeof value === "string" && value.length > 0)
    )
    if (persistedClientIds.size === 0) {
      return
    }

    setPendingUserMessages((current) =>
      current.filter((message) => !persistedClientIds.has(message.clientMessageId))
    )
  }, [])

  const handleConversationCreated = useCallback(
    (createdConversationId: string) => {
      setNewConversationDialogOpen(false)
      if (selectedConversationId === createdConversationId) {
        return
      }

      void navigate({
        to: "/conversations/$conversationId",
        params: { conversationId: createdConversationId },
      })
    },
    [navigate, selectedConversationId]
  )

  const stream = useAgentStream({
    onConversationCreated: handleConversationCreated,
  })

  const contextValue: ConversationWorkspaceContextValue = useMemo(
    () => ({
      addPendingUserMessage,
      clearPersistedPendingMessages,
      conversations,
      pendingUserMessages,
      removePendingUserMessage,
      stream,
    }),
    [
      addPendingUserMessage,
      clearPersistedPendingMessages,
      conversations,
      pendingUserMessages,
      removePendingUserMessage,
      stream,
    ]
  )

  return (
    <ConversationWorkspaceContext value={contextValue}>
      <div className="flex min-h-[calc(100vh-8rem)] flex-col gap-4">
        <div className="flex flex-col justify-between gap-4 md:flex-row md:items-start">
          <div className="flex min-w-0 flex-col gap-2">
            <p className="text-muted-foreground text-sm font-medium">Agent workspace</p>
            <h1 className="font-heading text-2xl font-semibold tracking-normal">Conversations</h1>
          </div>
          <NewConversationDialog
            agents={agentsData.agents}
            open={newConversationDialogOpen}
            onOpenChange={setNewConversationDialogOpen}
          />
        </div>

        <div className="grid min-h-0 flex-1 gap-4 lg:grid-cols-[320px_minmax(0,1fr)]">
          <aside className="bg-background flex min-h-0 flex-col rounded-xl border">
            <div className="flex items-center justify-between gap-3 p-3">
              <div className="min-w-0">
                <p className="text-sm font-medium">
                  {conversationsData.total} {pluralize(conversationsData.total, "conversation")}
                </p>
                <p className="text-muted-foreground text-xs">Recent activity first</p>
              </div>
              <Button
                size="icon-sm"
                variant="outline"
                aria-label="Open conversation start"
                render={<Link to="/conversations" />}
              >
                <PlusIcon />
              </Button>
            </div>
            <Separator />
            <div className="min-h-0 flex-1 overflow-y-auto p-2">
              <ConversationList
                conversations={conversations}
                selectedConversationId={selectedConversationId}
              />
            </div>
          </aside>

          <section className="bg-background min-w-0 rounded-xl border">
            {selectedConversationId ? <Outlet /> : <ConversationStartPanel />}
          </section>
        </div>
      </div>
    </ConversationWorkspaceContext>
  )
}

function NewConversationDialog({
  agents,
  open,
  onOpenChange,
}: {
  agents: Agent[]
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogTrigger render={<Button />}>
        <MessageSquarePlusIcon data-icon="inline-start" />
        New conversation
      </DialogTrigger>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>New conversation</DialogTitle>
          <DialogDescription>Choose an active agent and send the first prompt.</DialogDescription>
        </DialogHeader>
        <ConversationComposer mode="create" agents={agents} compact />
      </DialogContent>
    </Dialog>
  )
}

function ConversationStartPanel() {
  return (
    <div className="flex min-h-[520px] flex-col items-center justify-center p-8 text-center">
      <div className="bg-muted text-muted-foreground mb-4 flex size-11 items-center justify-center rounded-full">
        <MessageSquarePlusIcon className="size-5" />
      </div>
      <h2 className="font-heading text-xl font-semibold">Open a conversation</h2>
      <p className="text-muted-foreground mt-2 max-w-md text-sm">
        Select an existing thread from the list, or start a new one with an active agent.
      </p>
    </div>
  )
}

function sortConversations(conversations: ConversationWorkspaceContextValue["conversations"]) {
  return [...conversations].sort((left, right) => {
    const leftTime = Date.parse(left.last_message_at ?? left.updated_at)
    const rightTime = Date.parse(right.last_message_at ?? right.updated_at)
    return rightTime - leftTime
  })
}
