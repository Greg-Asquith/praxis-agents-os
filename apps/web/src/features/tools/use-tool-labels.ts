// apps/web/src/features/tools/use-tool-labels.ts

import { useCallback } from "react"

import { useToolPresentations } from "@/features/tools/use-tool-presentations"

export function useToolLabels() {
  const presentationFor = useToolPresentations()

  return useCallback((name: string) => presentationFor(name)?.label ?? name, [presentationFor])
}
