// apps/web/src/features/integrations/components/service-account-connect-dialog.tsx

import { useState, type SyntheticEvent } from "react"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Field, FieldDescription, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { useConnectServiceAccountMutation } from "@/features/integrations/api/connect-service-account"
import {
  validateServiceAccountConnectForm,
  type ServiceAccountConnectFormState,
} from "@/features/integrations/components/service-account-connect-form-model"
import type { IntegrationProvider } from "@/features/integrations/types"
import { getErrorMessage } from "@/lib/api/errors"
import { buildFieldErrors } from "@/lib/forms"

const EMPTY_FORM: ServiceAccountConnectFormState = { credentialsJson: "", label: "" }

export function ServiceAccountConnectForm({
  onCancel,
  onConnected,
  provider,
}: {
  onCancel: () => void
  onConnected: () => void
  provider: IntegrationProvider
}) {
  const [form, setForm] = useState<ServiceAccountConnectFormState>(EMPTY_FORM)
  const connectMutation = useConnectServiceAccountMutation(form.credentialsJson)
  const [error, setError] = useState<string | null>(null)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})

  async function handleSubmit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    const validation = validateServiceAccountConnectForm(form)
    setFieldErrors(buildFieldErrors(validation))
    if (validation.length > 0) {
      return
    }

    try {
      await connectMutation.mutateAsync({
        label: form.label.trim(),
        provider_key: provider.provider_key,
      })
      onConnected()
    } catch (mutationError) {
      setError(getErrorMessage(mutationError))
      setForm((current) => ({ ...current, credentialsJson: "" }))
      connectMutation.reset()
    }
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>Connect with a service account</DialogTitle>
        <DialogDescription>
          Use a Google Cloud service account that can access {provider.display_name}. The key is
          stored securely and cannot be viewed again.
        </DialogDescription>
      </DialogHeader>
      <form
        id={`connect-${provider.provider_key}-service-account`}
        onSubmit={(event) => {
          void handleSubmit(event)
        }}
      >
        <FieldGroup>
          {error ? (
            <Alert variant="destructive">
              <AlertTitle>Connection not added</AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          ) : null}
          <Field data-invalid={Boolean(fieldErrors["integration-connection-label"]) || undefined}>
            <FieldLabel htmlFor={`service-account-label-${provider.provider_key}`}>
              Connection Name
            </FieldLabel>
            <Input
              aria-invalid={Boolean(fieldErrors["integration-connection-label"]) || undefined}
              id={`service-account-label-${provider.provider_key}`}
              maxLength={120}
              onChange={(event) => {
                const label = event.currentTarget.value
                setForm((current) => ({ ...current, label }))
              }}
              placeholder={`Shared ${provider.display_name} connection`}
              value={form.label}
            />
            <FieldError>{fieldErrors["integration-connection-label"]}</FieldError>
          </Field>
          <Field
            data-invalid={Boolean(fieldErrors["integration-service-account-json"]) || undefined}
          >
            <FieldLabel htmlFor={`service-account-json-${provider.provider_key}`}>
              Service Account Key File
            </FieldLabel>
            <Textarea
              aria-invalid={Boolean(fieldErrors["integration-service-account-json"]) || undefined}
              autoComplete="off"
              className="min-h-40 resize-y text-xs"
              id={`service-account-json-${provider.provider_key}`}
              onChange={(event) => {
                const credentialsJson = event.currentTarget.value
                setForm((current) => ({
                  ...current,
                  credentialsJson,
                }))
              }}
              placeholder="Paste the contents of your key file"
              spellCheck={false}
              value={form.credentialsJson}
            />
            <FieldDescription>
              Paste the contents of the key file you downloaded from Google.
            </FieldDescription>
            <FieldError>{fieldErrors["integration-service-account-json"]}</FieldError>
          </Field>
        </FieldGroup>
      </form>
      <DialogFooter>
        <Button
          disabled={connectMutation.isPending}
          onClick={onCancel}
          type="button"
          variant="outline"
        >
          Cancel
        </Button>
        <Button
          disabled={connectMutation.isPending}
          form={`connect-${provider.provider_key}-service-account`}
          type="submit"
        >
          {connectMutation.isPending ? "Connecting" : "Connect Service Account"}
        </Button>
      </DialogFooter>
    </>
  )
}
