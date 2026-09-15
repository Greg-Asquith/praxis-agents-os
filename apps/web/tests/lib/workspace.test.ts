import { QueryClient } from "@tanstack/react-query"
import { artifactQueryOptions } from "@/features/artifacts/api/get-artifact"
import { platformArtifactQueryKeys } from "@/features/artifacts/api/platform-list-artifacts"
import { fileQueryOptions } from "@/features/files/api/get-file"
import { platformFilesQueryKeys } from "@/features/files/api/platform-list-files"
import { documentQueryOptions } from "@/features/knowledge/api/get-document"
import { platformKnowledgeQueryKeys } from "@/features/knowledge/api/platform-list-documents"
import { jsonResponse, stubFetch } from "../support/fetch-stub"
import { afterEach, describe, expect, it, vi } from "vitest"

import {
  activeUserQueryScope,
  activeWorkspaceQueryScope,
  clearActiveWorkspace,
  createWorkspaceScopedQueryKeys,
  setActiveUserId,
  setActiveWorkspaceSlug,
} from "@/lib/workspace"

afterEach(() => {
  clearActiveWorkspace()
  vi.unstubAllGlobals()
})

describe("workspace-scoped query keys", () => {
  it("uses the no-workspace sentinel when no workspace slug is active", () => {
    setActiveWorkspaceSlug(null)
    const userSentinel = ["__", "no", "_", "user", "__"].join("")
    const workspaceSentinel = ["__", "no", "_", "workspace", "__"].join("")

    expect(activeUserQueryScope()).toBe(userSentinel)
    expect(activeWorkspaceQueryScope()).toBe(workspaceSentinel)
    expect(createWorkspaceScopedQueryKeys("agents").workspace()).toEqual([
      "agents",
      userSentinel,
      workspaceSentinel,
    ])
  })

  it("scopes keys by user and workspace", () => {
    setActiveUserId("user-1")
    setActiveWorkspaceSlug("acme")
    const keys = createWorkspaceScopedQueryKeys("agents")
    const params = { includeInactive: true, limit: 50 }

    expect(keys.all).toEqual(["agents"])
    expect(keys.workspace()).toEqual(["agents", "user-1", "acme"])
    expect(keys.details()).toEqual(["agents", "user-1", "acme", "detail"])
    expect(keys.detail("agent-1")).toEqual(["agents", "user-1", "acme", "detail", "agent-1"])
    expect(keys.lists()).toEqual(["agents", "user-1", "acme", "list"])
    expect(keys.list(params)).toEqual(["agents", "user-1", "acme", "list", params])
  })
})

const platformReads = [
  {
    name: "Knowledge",
    load: (client: QueryClient) => client.fetchQuery(documentQueryOptions("shared")),
    managementKey: () => platformKnowledgeQueryKeys.detail("shared"),
  },
  {
    name: "Files",
    load: (client: QueryClient) => client.fetchQuery(fileQueryOptions("shared")),
    managementKey: () => platformFilesQueryKeys.detail("shared"),
  },
  {
    name: "Artifacts",
    load: (client: QueryClient) => client.fetchQuery(artifactQueryOptions("shared")),
    managementKey: () => platformArtifactQueryKeys.detail("shared"),
  },
]

describe("workspace switches with cached platform content", () => {
  it.each(platformReads)("refreshes $name access in the destination workspace", async (read) => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const fetch = stubFetch((_input, init) => {
      const workspace = new Headers(init?.headers).get("X-Workspace")
      if (workspace === "removed") {
        return jsonResponse({ detail: "Workspace access is unavailable" }, { status: 403 })
      }
      return jsonResponse({
        id: "shared",
        scope: "platform",
        workspace_id: null,
        is_published: true,
        can_manage_platform: false,
        can_edit: workspace === "editor",
      })
    })
    setActiveUserId("member")
    setActiveWorkspaceSlug("editor")
    expect(await read.load(client)).toMatchObject({ scope: "platform", can_edit: true })
    const editorManagementKey = read.managementKey()
    client.setQueryData(editorManagementKey, { id: "draft", can_manage_platform: true })

    setActiveWorkspaceSlug("reader")
    expect(client.getQueryData(read.managementKey())).toBeUndefined()
    expect(await read.load(client)).toMatchObject({
      scope: "platform",
      workspace_id: null,
      can_edit: false,
      can_manage_platform: false,
    })

    setActiveWorkspaceSlug("removed")
    await expect(read.load(client)).rejects.toThrow("Workspace access is unavailable")
    expect(fetch).toHaveBeenCalledTimes(3)
    expect(client.getQueryData(editorManagementKey)).toEqual({
      id: "draft",
      can_manage_platform: true,
    })
    client.clear()
  })
})
