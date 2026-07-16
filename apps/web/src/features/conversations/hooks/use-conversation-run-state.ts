// apps/web/src/features/conversations/hooks/use-conversation-run-state.ts

import { useEffect, useMemo } from "react"

import type { ConversationWorkspaceContextValue } from "@/features/conversations/conversation-workspace-context"
import type {
  AgentRun,
  ConversationMessage,
  PendingDelegatedApproval,
  PendingToolApproval,
} from "@/features/conversations/types"

type UseConversationRunStateParams = {
  activeRun: AgentRun | null
  conversationId: string
  messages: ConversationMessage[]
  recoveredApprovals: PendingToolApproval[]
  recoveredDelegations: PendingDelegatedApproval[]
  stream: ConversationWorkspaceContextValue["stream"]
  submittingApprovalRunId: string | null
}

export function useConversationRunState({
  activeRun,
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
  const hasPersistedStreamRun = useMemo(
    () =>
      streamRunId !== null &&
      messages.some((message) => message.metadata?.["agent_run_id"] === streamRunId),
    [messages, streamRunId]
  )
  const shouldRenderStream = shouldRenderConversationStream({
    activeRun,
    conversationId,
    hasPersistedStreamRun,
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
    if (streamConversationId !== conversationId) {
      return
    }

    const streamMatchesPendingApproval =
      activeRunStatus === "awaiting_approval" &&
      activeRunId !== null &&
      submittingApprovalRunId !== activeRunId &&
      streamRunId === activeRunId
    const streamMatchesPersistedSettledRun = activeRunId === null && hasPersistedStreamRun

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
    hasPersistedStreamRun,
    streamApprovalCount,
    streamConversationId,
    streamIsStreaming,
    streamRunId,
    streamToolCallCount,
    rawStreamMessages.length,
    resetStream,
    submittingApprovalRunId,
  ])

  return {
    pendingApprovals,
    pendingDelegations,
    shouldRenderStream,
    streamError:
      shouldRenderStream && streamConversationId === conversationId
        ? (streamErrorValue?.message ?? null)
        : null,
    streamMessages,
    streamToolCalls,
    visibleStreamApprovals,
  }
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

function shouldRenderConversationStream({
  activeRun,
  conversationId,
  hasPersistedStreamRun,
  streamConversationId,
  submittingApprovalRunId,
}: {
  activeRun: { id: string; status: string } | null
  conversationId: string
  hasPersistedStreamRun: boolean
  streamConversationId: string | null
  submittingApprovalRunId: string | null
}) {
  if (streamConversationId !== conversationId) {
    return false
  }

  if (activeRun === null && hasPersistedStreamRun) {
    return false
  }

  return activeRun?.status !== "awaiting_approval" || submittingApprovalRunId === activeRun.id
}
