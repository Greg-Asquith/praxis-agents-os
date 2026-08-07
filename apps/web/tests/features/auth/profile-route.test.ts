import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { describe, expect, it } from "vitest"

import { currentUserQueryKey } from "@/features/auth/api/get-current-user"
import { identitiesQueryKey } from "@/features/auth/api/get-identities"
import { oauthProvidersQueryOptions } from "@/features/auth/api/get-oauth-providers"
import { ProfileRoute } from "@/features/auth/routes/profile-route"
import type { AuthProvidersResponse, AuthUser, IdentitiesResponse } from "@/features/auth/types"

const user: AuthUser = {
  id: "user-a",
  email: "user-a@example.com",
  display_name: "User A",
  avatar_url: null,
  is_active: true,
  is_super_admin: false,
  default_workspace_id: null,
  totp_enabled: false,
  created_at: "2026-08-07T00:00:00Z",
  updated_at: "2026-08-07T00:00:00Z",
}

function renderProfile(emailAuthEnabled: boolean) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  const providers: AuthProvidersResponse = {
    email_auth_enabled: emailAuthEnabled,
    providers: [{ name: "google", display_name: "Google", icon: "google" }],
  }
  const identities: IdentitiesResponse = {
    has_password: true,
    identities: [
      {
        provider: "google",
        email: "user-a@example.com",
        email_verified: true,
        created_at: "2026-08-07T00:00:00Z",
      },
    ],
  }

  queryClient.setQueryData(currentUserQueryKey, user)
  queryClient.setQueryData(identitiesQueryKey, identities)
  queryClient.setQueryData(oauthProvidersQueryOptions().queryKey, providers)

  return renderToStaticMarkup(
    createElement(QueryClientProvider, { client: queryClient }, createElement(ProfileRoute))
  )
}

describe("ProfileRoute", () => {
  it("hides every password reference when email authentication is disabled", () => {
    const html = renderProfile(false)

    expect(html.toLowerCase()).not.toContain("password")
    expect(html).toContain("Manage your account details and security.")
    expect(html).toContain("Sign In Methods")
    expect(html).toContain("Two-Factor Authentication")
  })

  it("keeps password settings available when email authentication is enabled", () => {
    const html = renderProfile(true)

    expect(html).toContain("Manage your account details, password, and security.")
    expect(html).toContain("Change the password you use to sign in.")
    expect(html).toContain("Confirm your password before adding an authenticator.")
  })
})
