// apps/web/src/features/integrations/components/resource-selection-model.ts

import type { IntegrationResource } from "@/features/integrations/types"

export function integrationResourceIsRemoved(resource: IntegrationResource) {
  return resource.availability === "removed" || resource.removed_at !== null
}

export function integrationResourceIsManagerAccount(resource: IntegrationResource) {
  return resource.metadata["is_manager_account"] === true || resource.metadata["manager"] === true
}

export function integrationResourceIsSelectable(resource: IntegrationResource) {
  return !integrationResourceIsRemoved(resource) && !integrationResourceIsManagerAccount(resource)
}

export function enabledSelectableResourceIds(resources: IntegrationResource[]) {
  return resources
    .filter((resource) => resource.enabled && integrationResourceIsSelectable(resource))
    .map((resource) => resource.id)
}

export function resourcesInHierarchyOrder(resources: IntegrationResource[]) {
  const externalIds = new Set(resources.map((resource) => resource.external_id))
  const children = new Map<string | null, IntegrationResource[]>()
  for (const resource of resources) {
    const parent =
      resource.parent_external_id && externalIds.has(resource.parent_external_id)
        ? resource.parent_external_id
        : null
    children.set(parent, [...(children.get(parent) ?? []), resource])
  }

  const compareResources = (left: IntegrationResource, right: IntegrationResource) =>
    left.display_name.localeCompare(right.display_name) ||
    left.external_id.localeCompare(right.external_id)
  for (const siblings of children.values()) {
    siblings.sort(compareResources)
  }

  const ordered: IntegrationResource[] = []
  const visited = new Set<string>()
  function visit(resource: IntegrationResource) {
    if (visited.has(resource.id)) {
      return
    }
    visited.add(resource.id)
    ordered.push(resource)
    for (const child of children.get(resource.external_id) ?? []) {
      visit(child)
    }
  }

  for (const root of children.get(null) ?? []) {
    visit(root)
  }
  for (const resource of resources.toSorted(compareResources)) {
    visit(resource)
  }
  return ordered
}

export function resourcesWithExpandedParents(
  resources: IntegrationResource[],
  collapsedExternalIds: ReadonlySet<string>
) {
  const byExternalId = new Map(resources.map((resource) => [resource.external_id, resource]))
  return resources.filter((resource) => {
    const visited = new Set<string>()
    let parentExternalId = resource.parent_external_id
    while (parentExternalId && !visited.has(parentExternalId)) {
      if (collapsedExternalIds.has(parentExternalId)) {
        return false
      }
      visited.add(parentExternalId)
      parentExternalId = byExternalId.get(parentExternalId)?.parent_external_id ?? null
    }
    return true
  })
}

export function connectionResourcesAreEditable(canEdit: boolean, connectionStatus: string) {
  return canEdit && connectionStatus !== "revoked"
}
