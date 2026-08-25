// apps/web/src/features/integrations/api/update-table-scopes.ts

import { useMutation, useQueryClient } from "@tanstack/react-query"

import { integrationsQueryKeys } from "@/features/integrations/api/query-keys"
import type { TableScopeListResponse, TableScopeRuleInput } from "@/features/integrations/types"
import { apiRequest } from "@/lib/api/client"

async function updateTableScopes({
  connectionId,
  rules,
}: {
  connectionId: string
  rules: TableScopeRuleInput[]
}) {
  return apiRequest<TableScopeListResponse>(
    `/integrations/connections/${connectionId}/table-scopes`,
    { body: { rules }, method: "PUT" }
  )
}

export function useUpdateTableScopesMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: updateTableScopes,
    onSuccess: (response, { connectionId }) => {
      queryClient.setQueryData(integrationsQueryKeys.tableScopes(connectionId), response)
    },
  })
}
