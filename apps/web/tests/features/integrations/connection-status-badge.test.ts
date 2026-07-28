import { describe, expect, it } from "vitest"

import { connectionStatusPresentation } from "@/features/integrations/components/connection-status"

describe("connectionStatusPresentation", () => {
  it.each([
    ["auth_pending", "Connecting…", null, true],
    ["discovery_pending", "Finding your accounts…", null, true],
    ["needs_resource_selection", "Choose what agents can use", "select_resources", false],
    ["active", "Active", null, false],
    ["degraded", "Limited access", "retry_discovery", false],
    ["error", "Needs attention", "retry_discovery", false],
    ["revoked", "Disconnected", null, false],
  ] as const)("maps %s to its visible state", (status, label, action, pending) => {
    expect(connectionStatusPresentation({ status, supportsDiscovery: true })).toMatchObject({
      action,
      label,
      pending,
    })
  })

  it("maps credential recovery from the connection auth mode", () => {
    expect(
      connectionStatusPresentation({ authMode: "oauth", status: "needs_reauth" })
    ).toMatchObject({ action: "reauthenticate", label: "Sign in again" })
    expect(
      connectionStatusPresentation({ authMode: "service_account", status: "needs_credential" })
    ).toMatchObject({
      action: "replace_credential",
      label: "Replace Service Account Key",
    })
    expect(
      connectionStatusPresentation({ authMode: "api_key", status: "needs_credential" })
    ).toMatchObject({ action: "replace_credential", label: "Replace API key" })
  })

  it("fails safe for impossible pairs and unknown backend statuses", () => {
    expect(
      connectionStatusPresentation({ authMode: "service_account", status: "needs_reauth" })
    ).toEqual({
      action: null,
      label: "Needs attention",
      pending: false,
      variant: "destructive",
    })
    expect(connectionStatusPresentation({ status: "paused_by_provider" }).action).toBeNull()
  })
})
