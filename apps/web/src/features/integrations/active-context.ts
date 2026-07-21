// apps/web/src/features/integrations/active-context.ts

import type {
  ActiveContextSelectionValue,
  IntegrationContextGroup,
  IntegrationResource,
} from "@/features/integrations/types"

const NO_ACTIVE_CONTEXT = "none"

export function activeContextSelectionKey(value: ActiveContextSelectionValue | null) {
  if (value === null) {
    return NO_ACTIVE_CONTEXT
  }
  return value.type === "context_group"
    ? contextGroupSelectionKey(value.context_group_id)
    : resourceSelectionKey(value.integration_resource_id)
}

export function contextGroupSelectionKey(id: string) {
  return `group:${id}`
}

export function resourceSelectionKey(id: string) {
  return `resource:${id}`
}

export function activeContextSelectionLabel(
  value: ActiveContextSelectionValue | null,
  contextGroups: IntegrationContextGroup[],
  resources: IntegrationResource[]
) {
  if (value === null) {
    return "None"
  }
  if (value.type === "context_group") {
    return (
      contextGroups.find((group) => group.id === value.context_group_id)?.name ??
      "Context unavailable"
    )
  }
  return (
    resources.find((resource) => resource.id === value.integration_resource_id)?.display_name ??
    "Context unavailable"
  )
}
