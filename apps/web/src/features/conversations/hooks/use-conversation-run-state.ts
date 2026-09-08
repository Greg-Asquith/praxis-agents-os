// apps/web/src/features/conversations/hooks/use-conversation-run-state.ts

import { useEffect, useMemo } from "react"

import type { ConversationWorkspaceContextValue } from "@/features/conversations/conversation-workspace-context"
import type {
  AgentRun,
  ConversationMessage,
  PendingDelegatedApproval,
  PendingToolApproval,
} from "@/features/conversations/types"
import type { StreamError } from "@/features/conversations/stream/protocol"

const MODEL_PROVIDER_NOT_CONFIGURED = "model_provider_not_configured"

type UseConversationRunStateParams = {
  activeRun: AgentRun | null
  latestRun?: AgentRun | null
  conversationId: string
  messages: ConversationMessage[]
  recoveredApprovals: PendingToolApproval[]
  recoveredDelegations: PendingDelegatedApproval[]
  stream: ConversationWorkspaceContextValue["stream"]
  submittingApprovalRunId: string | null
}

export function useConversationRunState({
  activeRun,
  latestRun,
  conversationId,
  messages,
  recoveredApprovals,
  recoveredDelegations,
  stream,
  submittingApprovalRunId,
}: UseConversationRunStateParams) {
  const {
    approvals: streamApprovalsById,
    conversationId: streamConversationId,
    error: streamErrorValue,
    isStreaming: streamIsStreaming,
    isConnected: streamIsConnected,
    messages: rawStreamMessages,
    reset: resetStream,
    runId: streamRunId,
    toolCalls: streamToolCallsById,
  } = stream
  const activeRunId = activeRun?.id ?? null
  const activeRunStatus = activeRun?.status ?? null
  const streamToolCallCount = useMemo(
    () => Object.keys(streamToolCallsById).length,
    [streamToolCallsById]
  )
  const streamApprovalCount = useMemo(
    () => Object.keys(streamApprovalsById).length,
    [streamApprovalsById]
  )
  const hasPersistedStreamResponse = useMemo(
    () => hasPersistedRunResponse(messages, streamRunId),
    [messages, streamRunId]
  )
  const durableRunSettled =
    !streamIsConnected && activeRun === null && latestRun?.id === streamRunId
  const shouldRenderStream = shouldRenderConversationStream({
    durableRunSettled,
    activeRun,
    conversationId,
    hasPersistedStreamResponse,
    streamConversationId,
    submittingApprovalRunId,
  })
  const streamMessages = useMemo(
    () => (shouldRenderStream ? rawStreamMessages : []),
    [shouldRenderStream, rawStreamMessages]
  )
  const streamToolCalls = useMemo(
    () => (shouldRenderStream ? Object.values(streamToolCallsById) : []),
    [shouldRenderStream, streamToolCallsById]
  )
  const streamApprovals = useMemo(
    () => (streamConversationId === conversationId ? Object.values(streamApprovalsById) : []),
    [conversationId, streamApprovalsById, streamConversationId]
  )
  const visibleStreamApprovals = useMemo(
    () => (shouldRenderStream ? streamApprovals : []),
    [shouldRenderStream, streamApprovals]
  )
  const pendingApprovals = useMemo(
    () =>
      getPendingApprovals({
        activeRunId,
        recoveredApprovals,
        streamApprovals,
        streamRunId,
      }),
    [activeRunId, recoveredApprovals, streamApprovals, streamRunId]
  )
  const pendingDelegations = useMemo(
    () =>
      getPendingDelegations({
        activeRunId,
        recoveredDelegations,
        streamApprovals,
        streamRunId,
      }),
    [activeRunId, recoveredDelegations, streamApprovals, streamRunId]
  )

  // Reconcile shared stream state after server persistence or an approval transition settles it.
  useEffect(() => {
    if (streamConversationId !== conversationId || streamIsConnected) {
      return
    }

    const streamMatchesPendingApproval =
      activeRunStatus === "awaiting_approval" &&
      activeRunId !== null &&
      submittingApprovalRunId !== activeRunId &&
      streamRunId === activeRunId &&
      recoveredApprovals.length > 0
    const streamMatchesPersistedSettledRun =
      activeRunId === null && (hasPersistedStreamResponse || durableRunSettled)

    if (!streamMatchesPendingApproval && !streamMatchesPersistedSettledRun) {
      return
    }

    if (
      streamIsStreaming ||
      rawStreamMessages.length > 0 ||
      streamToolCallCount > 0 ||
      streamApprovalCount > 0
    ) {
      resetStream()
    }
  }, [
    activeRunId,
    activeRunStatus,
    conversationId,
    hasPersistedStreamResponse,
    durableRunSettled,
    streamApprovalCount,
    streamConversationId,
    streamIsStreaming,
    streamIsConnected,
    streamRunId,
    streamToolCallCount,
    rawStreamMessages.length,
    recoveredApprovals.length,
    resetStream,
    submittingApprovalRunId,
  ])

  return {
    pendingApprovals,
    pendingDelegations,
    shouldRenderStream,
    streamError:
      shouldRenderStream && streamConversationId === conversationId
        ? formatStreamError(streamErrorValue)
        : null,
    streamMessages,
    streamToolCalls,
    visibleStreamApprovals,
  }
}

export function formatStreamError(error: StreamError | null): string | null {
  if (error?.code === MODEL_PROVIDER_NOT_CONFIGURED) {
    return (
      `${error.message} Add the provider's API key to .local/targets/local.secrets.env ` +
      "(Docker stack) or apps/api/.env (make dev), then restart the system."
    )
  }
  return error?.message ?? null
}

function getPendingApprovals({
  activeRunId,
  recoveredApprovals,
  streamApprovals,
  streamRunId,
}: {
  activeRunId: string | null
  recoveredApprovals: PendingToolApproval[]
  streamApprovals: PendingToolApproval[]
  streamRunId: string | null
}) {
  if (recoveredApprovals.length > 0) {
    return recoveredApprovals
  }

  if (activeRunId !== null && streamRunId === activeRunId) {
    return streamApprovals
  }

  return []
}

function getPendingDelegations({
  activeRunId,
  recoveredDelegations,
  streamApprovals,
  streamRunId,
}: {
  activeRunId: string | null
  recoveredDelegations: PendingDelegatedApproval[]
  streamApprovals: PendingToolApproval[]
  streamRunId: string | null
}) {
  if (recoveredDelegations.length > 0) {
    return recoveredDelegations
  }

  if (activeRunId === null || streamRunId !== activeRunId) {
    return []
  }

  return streamApprovals.map((approval) => approval.delegation).filter(isPendingDelegatedApproval)
}

function isPendingDelegatedApproval(
  delegation: PendingDelegatedApproval | null | undefined
): delegation is PendingDelegatedApproval {
  return delegation !== null && delegation !== undefined
}

export function hasPersistedRunResponse(
  messages: ConversationMessage[],
  streamRunId: string | null
) {
  // The user prompt is persisted eagerly with this run id. Only an assistant
  // row proves that query data can replace the visible streamed response.
  return (
    streamRunId !== null &&
    messages.some(
      (message) =>
        message.role === "assistant" && message.metadata?.["agent_run_id"] === streamRunId
    )
  )
}

export function shouldRenderConversationStream({
  activeRun,
  durableRunSettled = false,
  conversationId,
  hasPersistedStreamResponse,
  streamConversationId,
  submittingApprovalRunId,
}: {
  activeRun: { id: string; status: string } | null
  durableRunSettled?: boolean
  conversationId: string
  hasPersistedStreamResponse: boolean
  streamConversationId: string | null
  submittingApprovalRunId: string | null
}) {
  if (durableRunSettled || streamConversationId !== conversationId) {
    return false
  }

  if (activeRun === null && hasPersistedStreamResponse) {
    return false
  }

  return activeRun?.status !== "awaiting_approval" || submittingApprovalRunId === activeRun.id
}
