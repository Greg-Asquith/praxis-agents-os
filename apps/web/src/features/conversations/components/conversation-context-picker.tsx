// apps/web/src/features/conversations/components/conversation-context-picker.tsx

import { useState } from "react"
import { useQuery } from "@tanstack/react-query"

import { useClearActiveContextMutation } from "@/features/integrations/api/clear-active-context"
import { activeContextQueryOptions } from "@/features/integrations/api/get-active-context"
import { contextGroupsQueryOptions } from "@/features/integrations/api/list-context-groups"
import { integrationResourcesQueryOptions } from "@/features/integrations/api/list-integration-resources"
import { useSetActiveContextMutation } from "@/features/integrations/api/set-active-context"
import { ContextSelect } from "@/features/integrations/components/context-select"
import type { ActiveContextSelectionValue } from "@/features/integrations/types"
import { useActiveWorkspace } from "@/features/workspaces/components/use-active-workspace"
import { getErrorMessage } from "@/lib/api/errors"

export function ConversationContextPicker({ conversationId }: { conversationId: string }) {
  const { workspace } = useActiveWorkspace()
  const activeContextQuery = useQuery(activeContextQueryOptions(conversationId))
  const contextGroupsQuery = useQuery(contextGroupsQueryOptions())
  const resourcesQuery = useQuery(integrationResourcesQueryOptions())
  const setMutation = useSetActiveContextMutation()
  const clearMutation = useClearActiveContextMutation()
  const [error, setError] = useState<string | null>(null)
  const pending = setMutation.isPending || clearMutation.isPending
  const queryUnavailable =
    activeContextQuery.isError || contextGroupsQuery.isError || resourcesQuery.isError
  const disabled =
    workspace.current_user_role === null ||
    workspace.current_user_role === "read_only" ||
    pending ||
    queryUnavailable ||
    activeContextQuery.isPending ||
    contextGroupsQuery.isPending ||
    resourcesQuery.isPending
  const activeContext = activeContextQuery.data ?? {
    entries: [],
    selection: null,
    unavailable: [],
  }

  async function handleChange(selection: ActiveContextSelectionValue | null) {
    setError(null)
    try {
      if (selection === null) {
        await clearMutation.mutateAsync(conversationId)
      } else {
        await setMutation.mutateAsync({ conversationId, selection })
      }
    } catch (mutationError) {
      setError(getErrorMessage(mutationError))
    }
  }

  return (
    <div
      className="flex min-w-0 items-center"
      title={
        error ?? (queryUnavailable ? "Integration context is temporarily unavailable" : undefined)
      }
    >
      <ContextSelect
        compact
        contextGroups={contextGroupsQuery.data?.items ?? []}
        disabled={disabled}
        hasUnavailable={activeContext.unavailable.length > 0}
        onChange={(selection) => {
          void handleChange(selection)
        }}
        resources={resourcesQuery.data ?? []}
        showManageIntegrations
        value={activeContext.selection}
      />
      <span aria-live="polite" className="sr-only">
        {error ?? (queryUnavailable ? "Integration context is temporarily unavailable" : "")}
      </span>
    </div>
  )
}

export function NewConversationContextPicker({
  disabled = false,
  onChange,
  value,
}: {
  disabled?: boolean
  onChange: (selection: ActiveContextSelectionValue | null) => void
  value: ActiveContextSelectionValue | null
}) {
  const { workspace } = useActiveWorkspace()
  const contextGroupsQuery = useQuery(contextGroupsQueryOptions())
  const resourcesQuery = useQuery(integrationResourcesQueryOptions())
  const queryUnavailable = contextGroupsQuery.isError || resourcesQuery.isError
  const pickerDisabled =
    disabled ||
    workspace.current_user_role === null ||
    workspace.current_user_role === "read_only" ||
    queryUnavailable ||
    contextGroupsQuery.isPending ||
    resourcesQuery.isPending

  return (
    <div
      className="flex min-w-0 items-center"
      title={queryUnavailable ? "Integration context is temporarily unavailable" : undefined}
    >
      <ContextSelect
        compact
        compactTitle="Active context · applies to the first run in this conversation"
        contextGroups={contextGroupsQuery.data?.items ?? []}
        disabled={pickerDisabled}
        onChange={onChange}
        resources={resourcesQuery.data ?? []}
        showManageIntegrations
        value={value}
      />
      <span aria-live="polite" className="sr-only">
        {queryUnavailable ? "Integration context is temporarily unavailable" : ""}
      </span>
    </div>
  )
}
