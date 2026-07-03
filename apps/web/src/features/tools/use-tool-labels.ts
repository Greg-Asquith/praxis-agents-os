// apps/web/src/features/tools/use-tool-labels.ts

import { useCallback, useMemo } from "react"
import { useQuery } from "@tanstack/react-query"

import { toolCatalogQueryOptions } from "@/features/tools/api/list-tool-catalog"

export function useToolLabels() {
  const { data } = useQuery(toolCatalogQueryOptions())
  const labels = useMemo(() => {
    return new Map((data?.tools ?? []).map((tool) => [tool.name, tool.label]))
  }, [data])

  return useCallback((name: string) => labels.get(name) ?? name, [labels])
}
