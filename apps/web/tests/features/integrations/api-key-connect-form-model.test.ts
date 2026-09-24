import { describe, expect, it } from "vitest"

import { validateApiKeyConnectForm } from "@/features/integrations/components/api-key-connect-form-model"

describe("validateApiKeyConnectForm", () => {
  it("requires a connection name and API key", () => {
    expect(validateApiKeyConnectForm({ apiKey: "  ", label: " " })).toEqual([
      {
        fieldId: "integration-connection-label",
        label: "Connection name",
        message: "Enter a name that identifies this connection.",
      },
      {
        fieldId: "integration-api-key",
        label: "API key",
        message: "Enter the API key for this provider.",
      },
    ])
  })

  it("accepts non-blank values", () => {
    expect(validateApiKeyConnectForm({ apiKey: "pat-secret", label: "Client base" })).toEqual([])
  })

  it("uses the provider credential label for validation", () => {
    expect(validateApiKeyConnectForm({ apiKey: "", label: "Agency" }, "Access token")).toEqual([
      {
        fieldId: "integration-api-key",
        label: "Access token",
        message: "Enter the Access token for this provider.",
      },
    ])
  })
})
