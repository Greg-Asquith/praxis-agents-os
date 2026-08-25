// apps/web/src/features/integrations/components/table-scope-editor-model.ts

import type {
  IntegrationResource,
  TableScopeRule,
  TableScopeRuleInput,
} from "@/features/integrations/types"

export function tableScopeResourceIsFilterable(resource: IntegrationResource) {
  return resource.enabled && resource.availability === "available"
}

export type TableScopeDraft = {
  id: string
  resourceId: string
  resourceDisplayName: string
  tableExternalId: string
  columnName: string
  columnType: "string" | "integer"
  allowedValues: string[]
}

export function tableScopeDrafts(rules: TableScopeRule[]): TableScopeDraft[] {
  return rules.map((rule) => ({
    id: rule.id,
    resourceId: rule.resource_id,
    resourceDisplayName: rule.resource_display_name,
    tableExternalId: rule.table_external_id,
    columnName: rule.column_name,
    columnType: rule.column_type,
    allowedValues: [...rule.allowed_values],
  }))
}

export function addTableScopeValues(current: string[], input: string): string[] {
  if (!input || current.includes(input)) {
    return current
  }
  return [...current, input]
}

export function tableScopeDraftError(
  draft: TableScopeDraft,
  otherDrafts: TableScopeDraft[]
): string | null {
  if (!draft.resourceId || !draft.tableExternalId || !draft.columnName) {
    return "Choose a data source, table, and column."
  }
  if (
    otherDrafts.some(
      (item) =>
        item.resourceId === draft.resourceId && item.tableExternalId === draft.tableExternalId
    )
  ) {
    return "This table already has a row filter."
  }
  if (draft.allowedValues.length === 0) {
    return "Add at least one allowed value."
  }
  if (draft.allowedValues.length > 200) {
    return "Add no more than 200 allowed values."
  }
  if (draft.allowedValues.some((value) => value.length === 0 || value.length > 256)) {
    return "Each value must contain 1–256 characters."
  }
  if (
    draft.columnType === "integer" &&
    draft.allowedValues.some((value) => !/^-?(?:0|[1-9][0-9]*)$/.test(value))
  ) {
    return "Use whole numbers for this column."
  }
  return null
}

export function tableScopeRuleInputs(drafts: TableScopeDraft[]): TableScopeRuleInput[] {
  return drafts.map((draft) => ({
    resource_id: draft.resourceId,
    table_external_id: draft.tableExternalId,
    column_name: draft.columnName,
    allowed_values: draft.allowedValues,
  }))
}

export function upsertTableScopeDraft(
  rules: TableScopeRule[],
  candidate: TableScopeDraft,
  editingRuleId: string | null
): TableScopeDraft[] {
  const drafts = tableScopeDrafts(rules)
  if (editingRuleId === null) {
    return [...drafts, candidate]
  }
  return drafts.map((draft) => (draft.id === editingRuleId ? candidate : draft))
}

export function removeTableScopeDraft(rules: TableScopeRule[], ruleId: string): TableScopeDraft[] {
  return tableScopeDrafts(rules.filter((rule) => rule.id !== ruleId))
}
