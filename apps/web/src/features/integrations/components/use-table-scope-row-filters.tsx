// apps/web/src/features/integrations/components/use-table-scope-row-filters.tsx

import { type ReactNode, useMemo, useRef, useState } from "react"

import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { useTableScopesQuery } from "@/features/integrations/api/list-table-scopes"
import { useUpdateTableScopesMutation } from "@/features/integrations/api/update-table-scopes"
import {
  type TableScopeDraft,
  removeTableScopeDraft,
  tableScopeDrafts,
  tableScopeRuleInputs,
  upsertTableScopeDraft,
} from "@/features/integrations/components/table-scope-editor-model"
import { TableScopeRuleDialog } from "@/features/integrations/components/table-scope-row-filters"
import type {
  IntegrationConnection,
  IntegrationResource,
  TableScopeRule,
} from "@/features/integrations/types"
import { getErrorMessage } from "@/lib/api/errors"

export type TableScopeRowFiltersController = {
  beginAdd: (resource: IntegrationResource) => void
  beginEdit: (rule: TableScopeRule) => void
  beginRemove: (rule: TableScopeRule) => void
  dialogs: ReactNode
  error: string | null
  pending: boolean
  rules: TableScopeRule[]
  rulesFor: (resourceId: string) => TableScopeRule[]
}

export function useTableScopeRowFilters(
  connection: IntegrationConnection
): TableScopeRowFiltersController {
  const { data } = useTableScopesQuery(connection.id)
  const mutation = useUpdateTableScopesMutation()
  const nextDraftId = useRef(0)
  const [editing, setEditing] = useState<TableScopeDraft | null>(null)
  const [editingRuleId, setEditingRuleId] = useState<string | null>(null)
  const [removing, setRemoving] = useState<TableScopeRule | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [dialogError, setDialogError] = useState<string | null>(null)
  const rules = data.rules
  const rulesByResource = useMemo(() => {
    const map = new Map<string, TableScopeRule[]>()
    for (const rule of rules) {
      const list = map.get(rule.resource_id) ?? []
      list.push(rule)
      map.set(rule.resource_id, list)
    }
    return map
  }, [rules])

  function beginAdd(resource: IntegrationResource) {
    nextDraftId.current += 1
    setError(null)
    setEditingRuleId(null)
    setDialogError(null)
    setEditing({
      allowedValues: [],
      columnName: "",
      columnType: "string",
      id: `new-${String(nextDraftId.current)}`,
      resourceDisplayName: resource.display_name,
      resourceId: resource.id,
      tableExternalId: "",
    })
  }

  function beginEdit(rule: TableScopeRule) {
    const [draft] = tableScopeDrafts([rule])
    if (!draft) {
      return
    }
    setError(null)
    setEditingRuleId(rule.id)
    setDialogError(null)
    setEditing(draft)
  }

  function closeEditor() {
    setEditing(null)
    setEditingRuleId(null)
    setDialogError(null)
  }

  async function acceptRule(candidate: TableScopeDraft) {
    setError(null)
    setDialogError(null)
    const next = upsertTableScopeDraft(rules, candidate, editingRuleId)
    try {
      await mutation.mutateAsync({
        connectionId: connection.id,
        rules: tableScopeRuleInputs(next),
      })
      closeEditor()
    } catch (mutationError) {
      setDialogError(getErrorMessage(mutationError))
    }
  }

  async function removeRule() {
    if (!removing) {
      return
    }
    setError(null)
    const next = removeTableScopeDraft(rules, removing.id)
    try {
      await mutation.mutateAsync({
        connectionId: connection.id,
        rules: tableScopeRuleInputs(next),
      })
    } catch (mutationError) {
      setError(getErrorMessage(mutationError))
    }
    setRemoving(null)
  }

  const dialogs = (
    <>
      {editing ? (
        <TableScopeRuleDialog
          connectionId={connection.id}
          draft={editing}
          error={dialogError}
          onAccept={(candidate) => void acceptRule(candidate)}
          onOpenChange={(open) => {
            if (!open) {
              closeEditor()
            }
          }}
          otherDrafts={tableScopeDrafts(rules.filter((rule) => rule.id !== editingRuleId))}
          pending={mutation.isPending}
        />
      ) : null}
      <ConfirmDialog
        confirmLabel="Remove Filter"
        confirmPendingLabel="Removing"
        description={
          removing ? `Agents will be able to read every row in ${removing.table_external_id}.` : ""
        }
        isPending={mutation.isPending}
        onConfirm={removeRule}
        onOpenChange={(open) => {
          if (!open) {
            setRemoving(null)
          }
        }}
        open={removing !== null}
        title="Remove Row Filter"
      />
    </>
  )

  return {
    beginAdd,
    beginEdit,
    beginRemove: setRemoving,
    dialogs,
    error,
    pending: mutation.isPending,
    rules,
    rulesFor: (resourceId) => rulesByResource.get(resourceId) ?? [],
  }
}
