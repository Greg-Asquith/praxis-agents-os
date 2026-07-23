import { describe, expect, it } from "vitest"

import { validateServiceAccountConnectForm } from "@/features/integrations/components/service-account-connect-form-model"

describe("validateServiceAccountConnectForm", () => {
  it("requires a connection name and service account JSON", () => {
    expect(validateServiceAccountConnectForm({ credentialsJson: " ", label: " " })).toEqual([
      {
        fieldId: "integration-connection-label",
        label: "Connection name",
        message: "Enter a name that identifies this connection.",
      },
      {
        fieldId: "integration-service-account-json",
        label: "Service account JSON",
        message: "Paste the service account JSON key.",
      },
    ])
  })

  it("rejects malformed JSON before submission", () => {
    expect(
      validateServiceAccountConnectForm({ credentialsJson: "not-json", label: "Google Ads" })
    ).toEqual([
      {
        fieldId: "integration-service-account-json",
        label: "Service account JSON",
        message: "Paste a valid JSON object.",
      },
    ])
  })

  it("accepts a JSON object and leaves credential validation to the API", () => {
    expect(
      validateServiceAccountConnectForm({
        credentialsJson: '{"type":"service_account"}',
        label: "Google Ads",
      })
    ).toEqual([])
  })
})
