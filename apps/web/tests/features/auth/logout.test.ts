import { QueryClient } from "@tanstack/react-query"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { currentUserQueryOptions } from "@/features/auth/api/get-current-user"
import { identitiesQueryOptions } from "@/features/auth/api/get-identities"
import { logoutMutationOptions } from "@/features/auth/api/logout"
import {
  ACTIVE_WORKSPACE_STORAGE_KEY,
  activeUserQueryScope,
  activeWorkspaceQueryScope,
  setActiveUserId,
  setActiveWorkspaceSlug,
} from "@/lib/workspace"
import { getFetchRequest, jsonResponse, stubFetch } from "../../support/fetch-stub"

const storage = new Map<string, string>()

beforeEach(() => {
  storage.clear()
  vi.stubGlobal("window", {
    localStorage: {
      getItem: (key: string) => storage.get(key) ?? null,
      removeItem: (key: string) => storage.delete(key),
      setItem: (key: string, value: string) => storage.set(key, value),
    },
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("logout mutation", () => {
  it("clears private query data and resets the active workspace", async () => {
    const fetchStub = stubFetch(jsonResponse({ message: "Signed out" }))
    const queryClient = new QueryClient()
    queryClient.setQueryData(currentUserQueryOptions().queryKey, {
      id: "user-a",
      email: "user-a@example.com",
      display_name: "User A",
      avatar_url: null,
      is_active: true,
      is_super_admin: false,
      default_workspace_id: "workspace-a",
      totp_enabled: false,
      created_at: "2026-07-30T00:00:00Z",
      updated_at: "2026-07-30T00:00:00Z",
    })
    queryClient.setQueryData(identitiesQueryOptions().queryKey, {
      has_password: true,
      identities: [
        {
          provider: "google",
          email: "user-a@example.com",
          email_verified: true,
          created_at: "2026-07-30T00:00:00Z",
        },
      ],
    })
    setActiveUserId("user-a")
    setActiveWorkspaceSlug("acme")
    window.localStorage.setItem(ACTIVE_WORKSPACE_STORAGE_KEY, "acme")

    const mutation = queryClient
      .getMutationCache()
      .build(queryClient, logoutMutationOptions(queryClient))
    await mutation.execute(undefined)

    const { init, url } = getFetchRequest(fetchStub)
    expect(url.href).toBe("http://localhost:8000/api/v1/auth/logout")
    expect(init).toMatchObject({ credentials: "include", method: "POST" })
    expect(new Headers(init.headers).get("X-Workspace")).toBe("acme")
    expect(queryClient.getQueryCache().getAll()).toHaveLength(0)
    expect(window.localStorage.getItem(ACTIVE_WORKSPACE_STORAGE_KEY)).toBeNull()
    expect(activeUserQueryScope()).toBe("__no_user__")
    expect(activeWorkspaceQueryScope()).toBe("__no_workspace__")
  })

  it("clears local authenticated state when the server logout fails", async () => {
    stubFetch(jsonResponse({ detail: "Server unavailable" }, { status: 503 }))
    const queryClient = new QueryClient()
    queryClient.setQueryData(identitiesQueryOptions().queryKey, {
      has_password: true,
      identities: [],
    })
    setActiveUserId("user-a")
    setActiveWorkspaceSlug("acme")
    window.localStorage.setItem(ACTIVE_WORKSPACE_STORAGE_KEY, "acme")

    const mutation = queryClient
      .getMutationCache()
      .build(queryClient, logoutMutationOptions(queryClient))

    await expect(mutation.execute(undefined)).rejects.toThrow("Server unavailable")
    expect(queryClient.getQueryCache().getAll()).toHaveLength(0)
    expect(window.localStorage.getItem(ACTIVE_WORKSPACE_STORAGE_KEY)).toBeNull()
    expect(activeUserQueryScope()).toBe("__no_user__")
    expect(activeWorkspaceQueryScope()).toBe("__no_workspace__")
  })
})
