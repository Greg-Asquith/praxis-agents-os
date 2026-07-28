// apps/web/src/features/integrations/components/service-account-connect-dialog.tsx

import { useState, type SyntheticEvent } from "react"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Field, FieldDescription, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { useConnectServiceAccountMutation } from "@/features/integrations/api/connect-service-account"
import { useReplaceCredentialMutation } from "@/features/integrations/api/replace-credential"
import {
  validateServiceAccountConnectForm,
  type ServiceAccountConnectFormState,
} from "@/features/integrations/components/service-account-connect-form-model"
import type { IntegrationConnection, IntegrationProvider } from "@/features/integrations/types"
import { getErrorMessage } from "@/lib/api/errors"
import { buildFieldErrors } from "@/lib/forms"

const EMPTY_FORM: ServiceAccountConnectFormState = { credentialsJson: "", label: "" }

export function ServiceAccountConnectForm({
  onCancel,
  onConnected,
  provider,
  replacementConnection,
}: {
  onCancel: () => void
  onConnected: () => void
  provider: IntegrationProvider
  replacementConnection?: IntegrationConnection
}) {
  const [form, setForm] = useState<ServiceAccountConnectFormState>(() => ({
    ...EMPTY_FORM,
    label: replacementConnection?.label ?? "",
  }))
  const connectMutation = useConnectServiceAccountMutation(form.credentialsJson)
  const replacementMutation = useReplaceCredentialMutation(replacementConnection?.id ?? "", {
    service_account_json: form.credentialsJson,
  })
  const activeMutation = replacementConnection ? replacementMutation : connectMutation
  const [error, setError] = useState<string | null>(null)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})

  async function handleSubmit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    const validation = validateServiceAccountConnectForm(form)
    setFieldErrors(buildFieldErrors(validation))
    if (validation.length > 0) {
      setForm((current) => ({ ...current, credentialsJson: "" }))
      return
    }

    try {
      if (replacementConnection) {
        await replacementMutation.mutateAsync()
      } else {
        await connectMutation.mutateAsync({
          label: form.label.trim(),
          provider_key: provider.provider_key,
        })
      }
      onConnected()
    } catch (mutationError) {
      setError(getErrorMessage(mutationError))
    } finally {
      setForm((current) => ({ ...current, credentialsJson: "" }))
      connectMutation.reset()
      replacementMutation.reset()
    }
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>
          {replacementConnection ? "Replace Service Account Key" : "Connect with a service account"}
        </DialogTitle>
        <DialogDescription>
          {replacementConnection
            ? `Paste a new key for ${replacementConnection.label}. We will check it in the background without changing the connection.`
            : `Use a Google Cloud service account that can access ${provider.display_name}. The key is stored securely and cannot be viewed again.`}
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
              <AlertTitle>
                {replacementConnection ? "Credential not replaced" : "Connection not added"}
              </AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          ) : null}
          {replacementConnection ? null : (
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
          )}
          <ServiceAccountKeyField
            error={fieldErrors["integration-service-account-json"]}
            onChange={(credentialsJson) => {
              setForm((current) => ({
                ...current,
                credentialsJson,
              }))
            }}
            providerKey={provider.provider_key}
            value={form.credentialsJson}
          />
        </FieldGroup>
      </form>
      <DialogFooter>
        <Button
          disabled={activeMutation.isPending}
          onClick={onCancel}
          type="button"
          variant="outline"
        >
          Cancel
        </Button>
        <Button
          disabled={activeMutation.isPending}
          form={`connect-${provider.provider_key}-service-account`}
          type="submit"
        >
          {activeMutation.isPending
            ? replacementConnection
              ? "Replacing"
              : "Connecting"
            : replacementConnection
              ? "Replace Service Account Key"
              : "Connect Service Account"}
        </Button>
      </DialogFooter>
    </>
  )
}

export function ServiceAccountKeyField({
  error,
  onChange,
  providerKey,
  value,
}: {
  error: string | undefined
  onChange: (value: string) => void
  providerKey: string
  value: string
}) {
  return (
    <Field data-invalid={Boolean(error) || undefined}>
      <FieldLabel htmlFor={`service-account-json-${providerKey}`}>
        Service Account Key File
      </FieldLabel>
      <Input
        aria-invalid={Boolean(error) || undefined}
        autoComplete="off"
        className="font-mono text-xs"
        id={`service-account-json-${providerKey}`}
        onChange={(event) => {
          onChange(event.currentTarget.value)
        }}
        placeholder="Paste the contents of your key file"
        spellCheck={false}
        type="password"
        value={value}
      />
      <FieldDescription>
        Paste the contents of the key file you downloaded from Google.
      </FieldDescription>
      <FieldError>{error}</FieldError>
    </Field>
  )
}
