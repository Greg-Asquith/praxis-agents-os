// apps/web/src/lib/integration-query-keys.ts

import { createWorkspaceScopedQueryKeys } from "@/lib/workspace"

// Provider-specific caches descend from connection details so detail invalidation reaches them.
export const baseIntegrationQueryKeys = createWorkspaceScopedQueryKeys("integrations")
