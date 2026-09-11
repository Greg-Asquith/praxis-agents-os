import { QueryClient } from "@tanstack/react-query"
import { afterEach, describe, expect, it } from "vitest"

import { artifactQueryOptions } from "@/features/artifacts/api/get-artifact"
import { artifactsQueryOptions } from "@/features/artifacts/api/list-artifacts"
import { platformArtifactQueryOptions } from "@/features/artifacts/api/platform-get-artifact"
import {
  applyPlatformArtifactChange,
  platformArtifactsQueryOptions,
} from "@/features/artifacts/api/platform-list-artifacts"
import type { PlatformArtifact } from "@/features/artifacts/types"
import { clearActiveWorkspace, setActiveUserId, setActiveWorkspaceSlug } from "@/lib/workspace"

afterEach(() => {
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

  it("seeds both detail caches and resets artifact caches across workspaces", async () => {
    const client = new QueryClient()
    setActiveUserId("user-1")
    setActiveWorkspaceSlug("acme")
    const page = { items: [], total: 0, limit: 25, offset: 0 }
    const acmeKey = artifactsQueryOptions({ limit: 25 }).queryKey
    client.setQueryData(acmeKey, page)
    setActiveWorkspaceSlug("other")
    const otherKey = artifactsQueryOptions({ limit: 25 }).queryKey
    client.setQueryData(otherKey, page)
    const artifact = { id: "artifact", title: "Shared" } as PlatformArtifact

    await applyPlatformArtifactChange(client, artifact)

    expect(client.getQueryData(artifactQueryOptions("artifact").queryKey)).toBe(artifact)
    expect(client.getQueryData(platformArtifactQueryOptions("artifact").queryKey)).toBe(artifact)
    expect(client.getQueryState(acmeKey)?.isInvalidated).toBe(true)
    expect(client.getQueryState(otherKey)?.isInvalidated).toBe(true)
  })
})
