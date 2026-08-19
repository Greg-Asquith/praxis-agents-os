// apps/web/src/features/tools/api/query-keys.ts

import { createWorkspaceScopedQueryKeys } from "@/lib/workspace"

const baseToolsQueryKeys = createWorkspaceScopedQueryKeys("tools")

export const toolsQueryKeys = {
  ...baseToolsQueryKeys,
  catalog: () => [...baseToolsQueryKeys.workspace(), "catalog"] as const,
  presentations: () => [...baseToolsQueryKeys.workspace(), "presentations"] as const,
}
