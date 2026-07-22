import { describe, expect, it } from "vitest"

import { providerSummaryStatus } from "@/features/integrations/components/provider-status"
import type { IntegrationConnection, IntegrationProvider } from "@/features/integrations/types"

const provider: IntegrationProvider = {
  auth_modes: ["oauth"],
  capability_flags: [],
  configured: true,
  configured_auth_modes: { oauth: true },
  display_name: "Gmail",
  oauth_scopes: [],
  owner_scope: "user",
  provider_key: "gmail",
  required_form_fields: [],
  requires_discovery: true,
  resource_types: ["mailbox"],
}

function connection(status: IntegrationConnection["status"]): IntegrationConnection {
  return {
    connected_by_user_id: "user-1",
    created_at: "2026-07-22T10:00:00Z",
    credential: null,
    duplicate_of_connection_ids: [],
    id: `connection-${status}`,
    label: "Work",
    latest_discovery_run: null,
    owner_scope: "user",
    owner_user_id: "user-1",
    owner_workspace_id: null,
    provider_key: "gmail",
    status,
    status_reason: null,
    updated_at: "2026-07-22T10:00:00Z",
  }
}

describe("providerSummaryStatus", () => {
  it("uses the worst status first", () => {
    expect(
      providerSummaryStatus(provider, [connection("active"), connection("needs_reauth")])
    ).toEqual({ label: "Needs attention", tone: "attention", variant: "destructive" })
    expect(
      providerSummaryStatus(provider, [connection("active"), connection("discovery_pending")])
    ).toEqual({ label: "Setting up…", tone: "pending", variant: "warning" })
  })

  it("counts connected accounts and excludes revoked connections", () => {
    expect(providerSummaryStatus(provider, [connection("active"), connection("revoked")])).toEqual({
      label: "Connected · 1 account",
      tone: "connected",
      variant: "success",
    })
    expect(providerSummaryStatus(provider, [connection("active"), connection("degraded")])).toEqual(
      { label: "Connected · 2 accounts", tone: "connected", variant: "success" }
    )
  })

  it("distinguishes unavailable and disconnected providers", () => {
    expect(providerSummaryStatus(provider, [])).toEqual({
      label: "Not connected",
      tone: "quiet",
      variant: null,
    })
    expect(
      providerSummaryStatus(
        { ...provider, configured: false, configured_auth_modes: { oauth: false } },
        [connection("revoked")]
      )
    ).toEqual({ label: "Not available", tone: "unavailable", variant: "secondary" })
  })
})
