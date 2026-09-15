import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { afterEach, describe, expect, it, vi } from "vitest"

import { useUpdatePlatformArtifactMutation } from "@/features/artifacts/api/platform-update-artifact"
import { jsonResponse, stubFetch } from "../../../support/fetch-stub"
import { artifactQueryKeys, artifactsQueryOptions } from "@/features/artifacts/api/list-artifacts"
import { platformArtifactQueryOptions } from "@/features/artifacts/api/platform-get-artifact"
import {
  applyPlatformArtifactChange,
  platformArtifactQueryKeys,
  platformArtifactsQueryOptions,
} from "@/features/artifacts/api/platform-list-artifacts"
import { clearActiveWorkspace, setActiveUserId, setActiveWorkspaceSlug } from "@/lib/workspace"

afterEach(() => {
  vi.unstubAllGlobals()
  clearActiveWorkspace()
})

describe("platform artifact caches", () => {
  it("keeps management keys separate from tenant keys within a workspace", () => {
    setActiveUserId("user-1")
    setActiveWorkspaceSlug("acme")

    expect(platformArtifactsQueryOptions({ limit: 25, offset: 25 }).queryKey).toEqual([
      "platform-artifacts",
      "user-1",
      "acme",
      "list",
      { limit: 25, offset: 25 },
    ])
    expect(platformArtifactQueryOptions("artifact").queryKey).toEqual([
      "platform-artifacts",
      "user-1",
      "acme",
      "detail",
      "artifact",
    ])
  })

  it("invalidates cached lists and details without copying access state across workspaces", async () => {
    const client = new QueryClient()
    setActiveUserId("user-1")
    setActiveWorkspaceSlug("acme")
    const page = { items: [], total: 0, limit: 25, offset: 0 }
    const acmeKey = artifactsQueryOptions({ limit: 25 }).queryKey
    client.setQueryData(acmeKey, page)
    setActiveWorkspaceSlug("other")
    const otherKey = artifactsQueryOptions({ limit: 25 }).queryKey
    client.setQueryData(otherKey, page)
    const readerKey = artifactQueryKeys.detail("artifact")
    const managementKey = platformArtifactQueryKeys.detail("artifact")
    const readerArtifact = { id: "artifact", scope: "platform", can_edit: false }
    client.setQueryData(readerKey, readerArtifact)
    client.setQueryData(managementKey, { ...readerArtifact, can_edit: true })

    await applyPlatformArtifactChange(client)

    expect(client.getQueryData(readerKey)).toEqual(readerArtifact)
    expect(client.getQueryState(readerKey)?.isInvalidated).toBe(true)
    expect(client.getQueryState(managementKey)?.isInvalidated).toBe(true)
    expect(client.getQueryState(acmeKey)?.isInvalidated).toBe(true)
    expect(client.getQueryState(otherKey)?.isInvalidated).toBe(true)
    client.clear()
  })
})

it("does not seed an editor response into a workspace switched to during save", async () => {
  const client = new QueryClient()
  setActiveUserId("user-1")
  setActiveWorkspaceSlug("editor")
  let save: ReturnType<typeof useUpdatePlatformArtifactMutation>["mutateAsync"] | undefined
  function MutationHarness() {
    save = useUpdatePlatformArtifactMutation().mutateAsync
    return null
  }
  renderToStaticMarkup(
    createElement(QueryClientProvider, {
      client,
      children: createElement(MutationHarness),
    })
  )
  const editorArtifact = { id: "artifact", scope: "platform", can_edit: true }
  const fetch = stubFetch(() => {
    setActiveWorkspaceSlug("reader")
    return jsonResponse(editorArtifact)
  })
  setActiveWorkspaceSlug("reader")
  const readerKey = artifactQueryKeys.detail("artifact")
  const readerArtifact = { ...editorArtifact, can_edit: false }
  client.setQueryData(readerKey, readerArtifact)
  setActiveWorkspaceSlug("editor")

  expect(save).toBeDefined()
  await save?.({ artifactId: "artifact", content: "Updated", expectedCurrentVersionId: "reviewed" })

  expect(fetch).toHaveBeenCalledOnce()
  expect(client.getQueryData(readerKey)).toEqual(readerArtifact)
  expect(client.getQueryState(readerKey)?.isInvalidated).toBe(true)
  expect(client.getQueryData(platformArtifactQueryOptions("artifact").queryKey)).toBeUndefined()
  client.clear()
})
