import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { describe, expect, it } from "vitest"

import { ConnectionRow } from "@/features/integrations/components/connection-row"
import { ServiceAccountKeyField } from "@/features/integrations/components/service-account-connect-dialog"
import { integrationAuthModeLabel } from "@/features/integrations/format"
import type { IntegrationConnection, IntegrationProvider } from "@/features/integrations/types"

const mixedModeGoogleAds: IntegrationProvider = {
  auth_modes: ["oauth", "service_account"],
  capability_flags: [],
  configured: true,
  configured_auth_modes: { oauth: true, service_account: true },
  display_name: "Google Ads",
  oauth_scopes: [],
  owner_scope: "workspace",
  provider_key: "google_ads",
  required_form_fields: [],
  requires_discovery: true,
  resource_types: ["customer_account"],
}

const serviceAccountConnection: IntegrationConnection = {
  connected_by_user_id: "user-1",
  created_at: "2026-07-28T10:00:00Z",
  credential: {
    auth_mode: "service_account",
    external_principal_label: "service@example.test",
    granted_scopes: null,
    last_refresh_error_code: null,
    last_refreshed_at: null,
    principal_fingerprint: "f".repeat(64),
    secret_reference: "local:reference#00000001",
    token_expires_at: null,
  },
  discovery_in_flight: false,
  duplicate_of_connection_ids: [],
  id: "connection-1",
  label: "Agency",
  latest_discovery_run: null,
  owner_scope: "workspace",
  owner_user_id: null,
  owner_workspace_id: "workspace-1",
  provider_key: "google_ads",
  status: "needs_credential",
  status_reason: "resource_discovery_auth_failed",
  updated_at: "2026-07-28T10:00:00Z",
}

describe("ConnectionRow", () => {
  it("never offers OAuth recovery for a mixed-mode service account", () => {
    const queryClient = new QueryClient()
    const html = renderToStaticMarkup(
      createElement(
        QueryClientProvider,
        { client: queryClient },
        createElement(ConnectionRow, {
          canEdit: true,
          canManageCredentials: true,
          connection: serviceAccountConnection,
          provider: mixedModeGoogleAds,
        })
      )
    )

    expect(html).toContain("Replace Service Account Key")
    expect(html).not.toContain("Sign in again")
    expect(html).not.toContain("Refresh Access")
  })

  it("uses the exact service account label", () => {
    expect(integrationAuthModeLabel("service_account")).toBe("Service Account Key")
  })

  it("obscures pasted service account JSON", () => {
    const queryClient = new QueryClient()
    const html = renderToStaticMarkup(
      createElement(
        QueryClientProvider,
        { client: queryClient },
        createElement(ServiceAccountKeyField, {
          error: undefined,
          onChange: () => undefined,
          providerKey: "google_ads",
          value: "",
        })
      )
    )

    expect(html).toContain('type="password"')
    expect(html).not.toContain("<textarea")
  })
})
