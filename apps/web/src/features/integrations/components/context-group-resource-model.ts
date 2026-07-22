// apps/web/src/features/integrations/components/context-group-resource-model.ts

import type { IntegrationResource } from "@/features/integrations/types"

export function eligibleContextGroupResources(
  resources: IntegrationResource[],
  isPersonalWorkspace: boolean
) {
  return resources.filter(
    (resource) =>
      resource.enabled &&
      resource.availability === "available" &&
      (resource.connection_status === "active" || resource.connection_status === "degraded") &&
      (isPersonalWorkspace || resource.connection_owner_scope === "workspace")
  )
}
