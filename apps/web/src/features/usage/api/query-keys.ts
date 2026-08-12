// apps/web/src/features/usage/api/query-keys.ts

import { createWorkspaceScopedQueryKeys } from "@/lib/workspace"

const baseUsageQueryKeys = createWorkspaceScopedQueryKeys("usage")

export const usageQueryKeys = {
  ...baseUsageQueryKeys,
  breakdown: (params: object) => [...baseUsageQueryKeys.workspace(), "breakdown", params] as const,
  summary: (params: object) => [...baseUsageQueryKeys.workspace(), "summary", params] as const,
}
