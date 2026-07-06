// apps/web/src/features/tools/use-tool-presentations.ts

import { useCallback, useMemo } from "react"
import { useQuery } from "@tanstack/react-query"

import { toolPresentationsQueryOptions } from "@/features/tools/api/list-tool-presentations"
import type { ToolPresentationEntry } from "@/features/tools/types"

export function useToolPresentations() {
  const { data } = useQuery(toolPresentationsQueryOptions())
  const entries = useMemo(() => {
    return new Map((data?.tools ?? []).map((tool) => [tool.name, tool]))
  }, [data])

  return useCallback(
    (name: string): ToolPresentationEntry | null => entries.get(name) ?? null,
    [entries]
  )
}
