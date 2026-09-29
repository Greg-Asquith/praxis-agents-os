// apps/web/src/features/tools/api/list-tool-settings.ts

import { queryOptions, useSuspenseQuery } from "@tanstack/react-query"

import { toolsQueryKeys } from "@/features/tools/api/query-keys"
import type { ToolSettingsResponse } from "@/features/tools/types"
import { apiRequest } from "@/lib/api/client"

async function listToolSettings() {
  return apiRequest<ToolSettingsResponse>("/tools/settings")
}

function toolSettingsQueryOptions() {
  return queryOptions({
    queryKey: toolsQueryKeys.settings(),
    queryFn: listToolSettings,
  })
}

export function useToolSettingsQuery() {
  return useSuspenseQuery(toolSettingsQueryOptions())
}
