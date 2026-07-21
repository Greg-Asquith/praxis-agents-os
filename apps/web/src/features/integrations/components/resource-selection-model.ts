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

export function connectionResourcesAreEditable(canEdit: boolean, connectionStatus: string) {
  return canEdit && connectionStatus !== "revoked"
}
