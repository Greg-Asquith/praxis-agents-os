// apps/web/src/features/integrations/components/api-key-connect-form-model.ts

import { DEFAULT_CREDENTIAL_LABEL } from "@/integrations/contract"
import type { FormValidationEntry } from "@/lib/forms"

export type ApiKeyConnectFormState = {
  label: string
  apiKey: string
}

export function validateApiKeyConnectForm(
  state: ApiKeyConnectFormState,
  credentialLabel = DEFAULT_CREDENTIAL_LABEL
): FormValidationEntry[] {
  const errors: FormValidationEntry[] = []
  if (!state.label.trim()) {
    errors.push({
      fieldId: "integration-connection-label",
      label: "Connection name",
      message: "Enter a name that identifies this connection.",
    })
  }
  if (!state.apiKey.trim()) {
    errors.push({
      fieldId: "integration-api-key",
      label: credentialLabel,
      message: `Enter the ${credentialLabel} for this provider.`,
    })
  }
  return errors
}
