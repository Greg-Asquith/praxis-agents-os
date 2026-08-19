import { QueryClient } from "@tanstack/react-query"
import { afterEach, describe, expect, it } from "vitest"

import { invalidateClassifierQueries } from "@/features/classifiers/api/invalidate-classifier-queries"
import { classifiersQueryKeys } from "@/features/classifiers/api/list-classifiers"
import { toolsQueryKeys } from "@/features/tools/api/query-keys"
import { clearActiveWorkspace, setActiveUserId, setActiveWorkspaceSlug } from "@/lib/workspace"

afterEach(() => {
  clearActiveWorkspace()
})

describe("invalidateClassifierQueries", () => {
  it("invalidates the classifier list and both workspace tool surfaces", async () => {
    setActiveUserId("user-1")
    setActiveWorkspaceSlug("acme")
    const queryClient = new QueryClient()
    const classifierKey = classifiersQueryKeys.list({ includeInactive: true })
    const catalogKey = toolsQueryKeys.catalog()
    const presentationsKey = toolsQueryKeys.presentations()
    const unrelatedKey = ["agents", "user-1", "acme"] as const
    queryClient.setQueryData(classifierKey, {})
    queryClient.setQueryData(catalogKey, {})
    queryClient.setQueryData(presentationsKey, {})
    queryClient.setQueryData(unrelatedKey, {})

    await invalidateClassifierQueries(queryClient)

    expect(queryClient.getQueryState(classifierKey)?.isInvalidated).toBe(true)
    expect(queryClient.getQueryState(catalogKey)?.isInvalidated).toBe(true)
    expect(queryClient.getQueryState(presentationsKey)?.isInvalidated).toBe(true)
    expect(queryClient.getQueryState(unrelatedKey)?.isInvalidated).toBe(false)
  })
})
