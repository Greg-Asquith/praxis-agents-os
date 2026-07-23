// apps/web/src/features/integrations/api/query-keys.ts

import { baseIntegrationQueryKeys } from "@/lib/integration-query-keys"

export const integrationsQueryKeys = {
  ...baseIntegrationQueryKeys,
  providers: () => [...baseIntegrationQueryKeys.workspace(), "providers"] as const,
  connections: () => [...baseIntegrationQueryKeys.workspace(), "connections"] as const,
  resources: (connectionId: string) =>
    [...baseIntegrationQueryKeys.detail(connectionId), "resources"] as const,
  enabledResources: () => [...baseIntegrationQueryKeys.workspace(), "enabled-resources"] as const,
  contextGroups: () => [...baseIntegrationQueryKeys.workspace(), "context-groups"] as const,
  activeContexts: () => [...baseIntegrationQueryKeys.workspace(), "active-context"] as const,
  activeContext: (conversationId: string) =>
    [...baseIntegrationQueryKeys.workspace(), "active-context", conversationId] as const,
}
