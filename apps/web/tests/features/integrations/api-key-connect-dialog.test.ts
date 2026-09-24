import { createElement } from "react"
import type * as React from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { beforeAll, describe, expect, it, vi } from "vitest"

import { Dialog } from "@/components/ui/dialog"
import { ApiKeyConnectForm } from "@/features/integrations/components/api-key-connect-dialog"
import { ConnectionRow } from "@/features/integrations/components/connection-row"
import type { IntegrationConnection, IntegrationProvider } from "@/features/integrations/types"
import { loadIntegrationUiModules } from "@/integrations/registry"

// Render the browser registry snapshot in the server-rendered component tests.
vi.mock("react", async (importOriginal) => ({
  ...(await importOriginal<typeof React>()),
  useSyncExternalStore: (_subscribe: unknown, getSnapshot: () => unknown) => getSnapshot(),
}))

function provider(providerKey: string): IntegrationProvider {
  return {
    auth_modes: ["api_key"],
    capability_flags: [],
    configured: true,
    configured_auth_modes: { api_key: true },
    display_name: providerKey === "meta_ads" ? "Meta Ads" : "Airtable",
    knowledge_source_resource_types: [],
    knowledge_source_supported: false,
    oauth_scopes: [],
    owner_scope: "workspace",
    provider_key: providerKey,
    required_form_fields: [providerKey === "meta_ads" ? "access_token" : "api_key"],
    requires_discovery: true,
    resource_types: [],
    table_scopes_supported: false,
  }
}

function connection(providerKey: string): IntegrationConnection {
  return {
    connected_by_user_id: "user-1",
    created_at: "2026-09-24T10:00:00Z",
    credential: {
      auth_mode: "api_key",
      external_principal_label: null,
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
    provider_key: providerKey,
    status: "needs_credential",
    status_reason: "resource_discovery_auth_failed",
    updated_at: "2026-09-24T10:00:00Z",
  }
}

describe("provider credential labels", () => {
  beforeAll(async () => {
    await loadIntegrationUiModules(["meta_ads", "airtable"])
  })

  it.each([
    ["meta_ads", "Access token"],
    ["airtable", "API key"],
  ])("uses %s's label for connect and replacement forms", (providerKey, label) => {
    for (const replace of [false, true]) {
      const html = renderToStaticMarkup(
        createElement(
          QueryClientProvider,
          { client: new QueryClient() },
          createElement(
            Dialog,
            { open: true },
            createElement(ApiKeyConnectForm, {
              onCancel: () => undefined,
              onConnected: () => undefined,
              provider: provider(providerKey),
              ...(replace ? { replacementConnection: connection(providerKey) } : {}),
            })
          )
        )
      )

      expect(html).toContain(`>${label}</label>`)
      expect(html).toContain('type="password"')
      expect(html).not.toContain("Required fields:")
      if (replace) {
        expect(html.match(new RegExp(`Replace ${label}`, "g"))).toHaveLength(2)
      }
      if (providerKey === "meta_ads") {
        expect(html).not.toContain("API key")
      }
    }
  })

  it.each([
    ["meta_ads", "Access token"],
    ["airtable", "API key"],
  ])("uses %s's label for the recovery badge and action", (providerKey, label) => {
    const html = renderToStaticMarkup(
      createElement(
        QueryClientProvider,
        { client: new QueryClient() },
        createElement(ConnectionRow, {
          canEdit: true,
          canManageCredentials: true,
          connection: connection(providerKey),
          provider: provider(providerKey),
        })
      )
    )

    expect(html.match(new RegExp(`Replace ${label}`, "g"))).toHaveLength(2)
    if (providerKey === "meta_ads") {
      expect(html).not.toContain("API key")
    }
  })
})
