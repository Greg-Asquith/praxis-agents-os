import { describe, expect, it } from "vitest"

import { connectionStatusPresentation } from "@/features/integrations/components/connection-status"

describe("connectionStatusPresentation", () => {
  it.each([
    ["auth_pending", "Connecting", null, true],
    ["discovery_pending", "Finding resources", null, true],
    ["needs_resource_selection", "Select resources", "select_resources", false],
    ["active", "Active", null, false],
    ["degraded", "Limited", null, false],
    ["error", "Needs attention", "retry_test", false],
    ["revoked", "Revoked", null, false],
    ["needs_reauth", "Reconnect", "reauthenticate", false],
  ] as const)("maps %s to its visible state", (status, label, action, pending) => {
    expect(connectionStatusPresentation(status)).toMatchObject({ action, label, pending })
  })

  it("shows an unknown backend status without crashing", () => {
    expect(connectionStatusPresentation("paused_by_provider")).toEqual({
      action: null,
      label: "paused_by_provider",
      pending: false,
      variant: "outline",
    })
  })
})
