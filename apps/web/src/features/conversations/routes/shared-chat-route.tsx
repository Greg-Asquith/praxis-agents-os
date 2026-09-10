// apps/web/src/features/conversations/routes/shared-chat-route.tsx

import { useEffect, useMemo } from "react"
import { Link, Navigate, useParams } from "@tanstack/react-router"
import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query"
import { EyeIcon, RefreshCwIcon } from "lucide-react"

import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { EmptyState } from "@/components/ui/empty-state"
import { conversationQueryOptions } from "@/features/conversations/api/get-conversation"
import { conversationsQueryKeys } from "@/features/conversations/api/list-conversations"
import {
  clearSharedChat,
  sharedChatQueryOptions,
} from "@/features/conversations/api/get-shared-chat"
import { ConversationSharingDialog } from "@/features/conversations/components/conversation-sharing-dialog"
import { RunStatusBadge } from "@/features/conversations/components/run-status-badge"
import { MessageList } from "@/features/conversations/components/message-list"
import { projectConversationTimeline } from "@/features/conversations/message-parts/timeline"
import { useActiveWorkspace } from "@/features/workspaces/components/use-active-workspace"
import { formatCompactDate } from "@/lib/format"

export function SharedChatRoute() {
  const { workspaceId, conversationId } = useParams({ strict: false })
  const { workspace, workspaces, setWorkspaceBySlug } = useActiveWorkspace()
  const target = workspaces.find(
    (item) =>
      item.id === workspaceId &&
      item.status === "active" &&
      !item.deleted &&
      item.current_user_role !== null
  )
  useEffect(() => {
    if (target && target.id !== workspace.id) setWorkspaceBySlug(target.slug, { persist: false })
  }, [target, workspace.id, setWorkspaceBySlug])
  if (!conversationId || !target) return <SharedChatUnavailable />
  if (workspace.id !== target.id) return <p role="status">Opening workspace…</p>
  return (
    <SharedChatViewer key={`${workspace.id}:${conversationId}`} conversationId={conversationId} />
  )
}

export function SharedChatUnavailable() {
  return (
    <EmptyState
      title="Chat unavailable"
      description="This chat is unavailable or you no longer have access to it."
      action={
        <Button variant="outline" render={<Link to="/conversations" />}>
          Open my chats
        </Button>
      }
    />
  )
}

function SharedChatViewer({ conversationId }: { conversationId: string }) {
  const queryClient = useQueryClient()
  const detailOptions = conversationQueryOptions(conversationId)
  const detail = useQuery({ ...detailOptions, staleTime: 0, gcTime: 0, retry: false })
  const options = sharedChatQueryOptions(conversationId)
  const query = useInfiniteQuery({ ...options, enabled: detail.data?.access === "viewer" })
  const data = detail.data
  const pages = query.data?.pages
  const accessLost = data === null || Boolean(pages?.some((page) => page === null))
  const refresh = () => {
    void detail.refetch()
    void query.refetch()
  }
  useEffect(() => {
    if (accessLost && !(data === null && pages?.length === 1 && pages[0] === null)) {
      void clearSharedChat(queryClient, {
        detail: detailOptions.queryKey,
        messages: conversationsQueryKeys.messages(conversationId),
        shared: options.queryKey,
      })
    }
  }, [
    accessLost,
    data,
    pages,
    queryClient,
    conversationId,
    detailOptions.queryKey,
    options.queryKey,
  ])
  const timeline = useMemo(
    () =>
      projectConversationTimeline({
        conversationId,
        assistantAgentId: "shared-agent",
        messages: (pages?.toReversed().flatMap((page) => page?.messages ?? []) ?? []).filter(
          (message) => {
            const parts = message.parts["parts"]
            return !Array.isArray(parts) || parts.length > 0
          }
        ),
        approvals: [],
        pendingDelegations: [],
        pendingUserMessages: [],
        pendingWorkflow: null,
        transcriptRun: null,
        readOnly: true,
        stream: {
          approvals: [],
          conversationId: null,
          isStreaming: false,
          messages: [],
          runId: null,
          toolCalls: [],
        },
      }),
    [conversationId, pages]
  )
  if (accessLost) return <SharedChatUnavailable />
  if (data && data.access !== "viewer")
    return <Navigate replace to="/conversations/$conversationId" params={{ conversationId }} />
  if (!data || !query.data)
    return (
      <p role="status">
        {query.error || detail.error
          ? "The chat could not refresh. Check your connection and try again."
          : "Loading chat…"}
        <Button variant="outline" onClick={refresh}>
          Refresh
        </Button>
      </p>
    )
  const conversation = data
  return (
    <div className="bg-background flex h-full min-h-0 min-w-0 flex-col overflow-hidden">
      <header className="flex min-h-16 shrink-0 flex-wrap items-center justify-between gap-x-3 gap-y-1 border-b px-4 py-2">
        <div className="flex min-w-0 flex-1 items-center gap-2">
          <h1 className="font-heading min-w-0 truncate text-base font-medium">
            {conversation.title ?? "Untitled conversation"}
          </h1>
          <Badge className="shrink-0" variant="outline">
            <EyeIcon aria-hidden="true" data-icon="inline-start" />
            View only
          </Badge>
          {conversation.active_run_status ? (
            <RunStatusBadge status={conversation.active_run_status} />
          ) : null}
          <span className="text-muted-foreground truncate text-xs">
            {conversation.owner_name
              ? `Shared by ${conversation.owner_name}`
              : "Shared with your workspace"}
          </span>
        </div>
        <div className="ml-auto flex shrink-0 items-center gap-2">
          <span className="text-muted-foreground text-xs">
            Refreshed {formatCompactDate(new Date(query.dataUpdatedAt).toISOString())}
          </span>
          <ConversationSharingDialog conversation={conversation} />
          <Button
            variant="outline"
            size="sm"
            disabled={query.isFetching || detail.isFetching}
            onClick={refresh}
          >
            <RefreshCwIcon data-icon="inline-start" />
            Refresh
          </Button>
        </div>
      </header>
      <p className="text-muted-foreground border-b px-4 py-2 text-xs">
        Only the chat owner can send messages. Later saved messages appear after refresh.
      </p>
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-4xl px-6 py-6 pb-8">
          {detail.error || (query.error && !query.isFetchNextPageError) ? (
            <Alert role="status" className="mb-4">
              <AlertDescription>
                The chat could not refresh. Check your connection and try again.
              </AlertDescription>
            </Alert>
          ) : null}
          {query.isFetchNextPageError ? (
            <Alert role="status" className="mb-4">
              <AlertDescription>Earlier messages could not load. Try again.</AlertDescription>
            </Alert>
          ) : null}
          {query.hasNextPage ? (
            <Button
              className="mb-4"
              variant="outline"
              disabled={query.isFetching || detail.isFetching}
              onClick={() => void query.fetchNextPage()}
            >
              {query.isFetchNextPageError
                ? "Retry earlier messages"
                : query.isFetchingNextPage
                  ? "Loading earlier messages…"
                  : "Load earlier messages"}
            </Button>
          ) : null}
          <MessageList
            shared
            timeline={timeline}
            assistantAgentMetadata={null}
            assistantLabel={conversation.agent_name ?? "Agent"}
          />
        </div>
      </div>
    </div>
  )
}
