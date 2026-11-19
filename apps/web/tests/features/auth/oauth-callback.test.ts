// apps/web/tests/features/auth/oauth-callback.test.ts

import { describe, expect, it } from "vitest"

import { isOauthLinkState } from "@/features/auth/oauth-callback"

function stateWith(payload: Record<string, string>) {
  return `header.${Buffer.from(JSON.stringify(payload)).toString("base64url")}.signature`
}

describe("OAuth callback state", () => {
  it("routes only link state to account linking", () => {
    expect(isOauthLinkState(stateWith({ type: "oauth_link_state", provider: "microsoft" }))).toBe(
      true
    )
    expect(isOauthLinkState(stateWith({ type: "oauth_state", provider: "microsoft" }))).toBe(false)
    expect(isOauthLinkState("not-a-jwt")).toBe(false)
  })
})
