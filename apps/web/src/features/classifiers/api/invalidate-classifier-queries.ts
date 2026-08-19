// apps/web/src/features/classifiers/api/invalidate-classifier-queries.ts

import type { QueryClient } from "@tanstack/react-query"

import { classifiersQueryKeys } from "@/features/classifiers/api/list-classifiers"
import { toolsQueryKeys } from "@/features/tools/api/query-keys"

export async function invalidateClassifierQueries(queryClient: QueryClient) {
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: classifiersQueryKeys.workspace() }),
    queryClient.invalidateQueries({ queryKey: toolsQueryKeys.workspace() }),
  ])
}
