// apps/web/src/features/integrations/components/service-account-connect-dialog.tsx

import { useState, type SyntheticEvent } from "react"
import { KeyRoundIcon } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
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

export function ServiceAccountConnectDialog({ provider }: { provider: IntegrationProvider }) {
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState<ServiceAccountConnectFormState>(EMPTY_FORM)
  const connectMutation = useConnectServiceAccountMutation(form.credentialsJson)
  const [error, setError] = useState<string | null>(null)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})

  function handleOpenChange(nextOpen: boolean) {
    setOpen(nextOpen)
    if (!nextOpen) {
      setForm(EMPTY_FORM)
      setError(null)
      setFieldErrors({})
      connectMutation.reset()
    }
  }

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
      handleOpenChange(false)
    } catch (mutationError) {
      setError(getErrorMessage(mutationError))
      setForm((current) => ({ ...current, credentialsJson: "" }))
      connectMutation.reset()
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger render={<Button size="sm" variant="outline" />}>
        <KeyRoundIcon data-icon="inline-start" />
        Use service account
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Connect with a service account</DialogTitle>
          <DialogDescription>
            Use a Google Cloud service account that has access to the required Google Ads manager
            account. The key is stored securely and cannot be viewed again.
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
                placeholder="Shared Google Ads account"
                value={form.label}
              />
              <FieldError>{fieldErrors["integration-connection-label"]}</FieldError>
            </Field>
            <Field
              data-invalid={Boolean(fieldErrors["integration-service-account-json"]) || undefined}
            >
              <FieldLabel htmlFor={`service-account-json-${provider.provider_key}`}>
                Service Account JSON
              </FieldLabel>
              <Textarea
                aria-invalid={Boolean(fieldErrors["integration-service-account-json"]) || undefined}
                autoComplete="off"
                className="min-h-40 resize-y font-mono text-xs"
                id={`service-account-json-${provider.provider_key}`}
                onChange={(event) => {
                  const credentialsJson = event.currentTarget.value
                  setForm((current) => ({
                    ...current,
                    credentialsJson,
                  }))
                }}
                placeholder={'{"type":"service_account", ...}'}
                spellCheck={false}
                value={form.credentialsJson}
              />
              <FieldDescription>
                Paste the complete JSON key downloaded from Google Cloud.
              </FieldDescription>
              <FieldError>{fieldErrors["integration-service-account-json"]}</FieldError>
            </Field>
          </FieldGroup>
        </form>
        <DialogFooter>
          <Button
            disabled={connectMutation.isPending}
            onClick={() => {
              handleOpenChange(false)
            }}
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
            {connectMutation.isPending ? "Connecting" : "Connect service account"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
