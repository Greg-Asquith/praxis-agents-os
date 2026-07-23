// apps/web/src/features/integrations/active-context.ts

import { formatIntegrationResourceValue } from "@/features/integrations/format"
import type {
  ActiveContextSelectionValue,
  IntegrationContextGroup,
  IntegrationResource,
} from "@/features/integrations/types"

const NO_ACTIVE_CONTEXT = "none"

export const MANAGE_INTEGRATIONS_SELECTION = "manage-integrations"

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

export function activeContextSelectionFromKey(
  key: string,
  contextGroups: IntegrationContextGroup[],
  resources: IntegrationResource[]
): ActiveContextSelectionValue | null | undefined {
  if (key === NO_ACTIVE_CONTEXT) {
    return null
  }
  const group = contextGroups.find((item) => contextGroupSelectionKey(item.id) === key)
  if (group) {
    return { context_group_id: group.id, type: "context_group" }
  }
  const resource = resources.find((item) => resourceSelectionKey(item.id) === key)
  if (resource) {
    return { integration_resource_id: resource.id, type: "resource" }
  }
  return undefined
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
  const resource = resources.find((item) => item.id === value.integration_resource_id)
  return resource
    ? formatIntegrationResourceValue(resource.provider_key, resource.display_name)
    : "Context unavailable"
}
