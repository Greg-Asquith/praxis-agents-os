// apps/web/src/features/tools/api/update-tool-setting.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { toolsQueryKeys } from "@/features/tools/api/query-keys"
import type { ToolCatalogPolicy } from "@/features/tools/types"
import { apiRequest } from "@/lib/api/client"

type UpdateToolSettingInput = {
  toolName: string
  enabled?: boolean
  policy?: ToolCatalogPolicy | null
}

export async function updateToolSetting({ toolName, enabled, policy }: UpdateToolSettingInput) {
  const path = `/tools/${encodeURIComponent(toolName)}`
  // Save the policy first so a tool being turned on never runs under its previous policy.
  if (policy !== undefined) {
    await apiRequest<unknown>(`${path}/policy`, { body: { policy }, method: "PUT" })
  }
  if (enabled !== undefined) {
    await apiRequest<unknown>(`${path}/availability`, { body: { enabled }, method: "PUT" })
  }
}

export function useUpdateToolSettingMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: updateToolSetting,
    // Refresh after failures too, since a policy can save before enablement fails.
    onSettled: async () => {
      await queryClient.invalidateQueries({ queryKey: toolsQueryKeys.workspace() })
    },
  })
}
