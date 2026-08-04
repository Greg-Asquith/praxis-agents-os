// apps/web/src/features/integrations/active-context.ts

import { formatIntegrationResourceValue } from "@/features/integrations/format"
import type {
  ActiveContextSelectionValue,
  IntegrationContextGroup,
  IntegrationResource,
} from "@/features/integrations/types"

export const MAX_ACTIVE_CONTEXT_TARGETS = 10

export function activeContextSelectionKey(value: ActiveContextSelectionValue) {
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
): ActiveContextSelectionValue | undefined {
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
  value: ActiveContextSelectionValue,
  contextGroups: IntegrationContextGroup[],
  resources: IntegrationResource[]
) {
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

export function activeContextTargetsKey(values: ActiveContextSelectionValue[]) {
  return values.map(activeContextSelectionKey).toSorted().join("|")
}

export function activeContextTargetsLabel(
  values: ActiveContextSelectionValue[],
  contextGroups: IntegrationContextGroup[],
  resources: IntegrationResource[]
) {
  const first = values[0]
  if (!first) {
    return "None"
  }
  const firstLabel = activeContextSelectionLabel(first, contextGroups, resources)
  return values.length === 1 ? firstLabel : `${firstLabel} +${String(values.length - 1)} more`
}

export function toggleActiveContextTarget(
  values: ActiveContextSelectionValue[],
  target: ActiveContextSelectionValue
) {
  const targetKey = activeContextSelectionKey(target)
  const selected = values.some((value) => activeContextSelectionKey(value) === targetKey)
  if (selected) {
    return values.filter((value) => activeContextSelectionKey(value) !== targetKey)
  }
  return values.length < MAX_ACTIVE_CONTEXT_TARGETS ? [...values, target] : values
}
