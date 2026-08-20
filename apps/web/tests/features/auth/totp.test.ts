import { QueryClient } from "@tanstack/react-query"
import { afterEach, describe, expect, it, vi } from "vitest"

import { currentUserQueryKey } from "@/features/auth/api/get-current-user"
import { totpVerificationRequest, verifyTotpMutationOptions } from "@/features/auth/api/totp"
import type { AuthResponse, AuthUser } from "@/features/auth/types"
import { getFetchRequest, jsonResponse, stubFetch } from "../../support/fetch-stub"

const user: AuthUser = {
  id: "user-a",
  email: "user-a@example.com",
  display_name: "User A",
  avatar_url: null,
  is_active: true,
  is_super_admin: false,
  default_workspace_id: "workspace-a",
  totp_enabled: true,
  created_at: "2026-07-30T00:00:00Z",
  updated_at: "2026-07-30T00:00:00Z",
}

const verifiedResponse: AuthResponse = {
  next_path: null,
  requires_twofa: false,
  session: {
    expires_at: "2026-07-31T00:00:00Z",
    twofa_verified: true,
  },
  user,
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("TOTP verification", () => {
  it("maps authenticator and backup codes to the backend contract", () => {
    expect(totpVerificationRequest("123456")).toEqual({ token: "123456" })
    expect(totpVerificationRequest("12345678")).toEqual({ backup_code: "12345678" })
  })

  it("upgrades the partial session and seeds the authenticated user cache", async () => {
    const fetchStub = stubFetch(jsonResponse(verifiedResponse))

    const queryClient = new QueryClient()
    const mutation = queryClient
      .getMutationCache()
      .build(queryClient, verifyTotpMutationOptions(queryClient))

    const response = await mutation.execute({ token: "123456" })

    expect(response).toEqual(verifiedResponse)
    expect(fetchStub).toHaveBeenCalledOnce()
    const { init, url } = getFetchRequest(fetchStub)
    expect(url.href).toBe("http://localhost:8000/api/v1/auth/totp/verify")
    expect(init).toMatchObject({
      body: JSON.stringify({ token: "123456" }),
      credentials: "include",
      method: "POST",
    })
    expect(new Headers(init.headers).get("Content-Type")).toBe("application/json")
    expect(queryClient.getQueryData(currentUserQueryKey)).toEqual(user)
  })
})
