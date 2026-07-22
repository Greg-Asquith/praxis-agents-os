// apps/web/src/features/integrations/components/service-account-connect-form-model.ts

import type { FormValidationEntry } from "@/lib/forms"

export type ServiceAccountConnectFormState = {
  label: string
  credentialsJson: string
}

export function validateServiceAccountConnectForm(
  state: ServiceAccountConnectFormState
): FormValidationEntry[] {
  const errors: FormValidationEntry[] = []
  if (!state.label.trim()) {
    errors.push({
      fieldId: "integration-connection-label",
      label: "Connection name",
      message: "Enter a name that identifies this connection.",
    })
  }
  if (!state.credentialsJson.trim()) {
    errors.push({
      fieldId: "integration-service-account-json",
      label: "Service account JSON",
      message: "Paste the service account JSON key.",
    })
  } else {
    try {
      const parsed: unknown = JSON.parse(state.credentialsJson)
      if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
        throw new Error("Not an object")
      }
    } catch {
      errors.push({
        fieldId: "integration-service-account-json",
        label: "Service account JSON",
        message: "Paste a valid JSON object.",
      })
    }
  }
  return errors
}
