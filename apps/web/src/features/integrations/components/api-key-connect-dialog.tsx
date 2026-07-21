// apps/web/src/features/integrations/components/api-key-connect-dialog.tsx

import { useState, type SyntheticEvent } from "react"
import { KeyRoundIcon, PlusIcon } from "lucide-react"

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
import { useConnectApiKeyMutation } from "@/features/integrations/api/connect-api-key"
import {
  validateApiKeyConnectForm,
  type ApiKeyConnectFormState,
} from "@/features/integrations/components/api-key-connect-form-model"
import type { IntegrationProvider } from "@/features/integrations/types"
import { getErrorMessage } from "@/lib/api/errors"
import { buildFieldErrors } from "@/lib/forms"

const EMPTY_FORM: ApiKeyConnectFormState = { apiKey: "", label: "" }

export function ApiKeyConnectDialog({ provider }: { provider: IntegrationProvider }) {
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState<ApiKeyConnectFormState>(EMPTY_FORM)
  const connectMutation = useConnectApiKeyMutation(form.apiKey)
  const [error, setError] = useState<string | null>(null)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})

  function handleOpenChange(nextOpen: boolean) {
    setOpen(nextOpen)
    if (!nextOpen) {
      setForm(EMPTY_FORM)
      setError(null)
      setFieldErrors({})
    }
  }

  async function handleSubmit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    const validation = validateApiKeyConnectForm(form)
    setFieldErrors(buildFieldErrors(validation))
    if (validation.length > 0) {
      setForm((current) => ({ ...current, apiKey: "" }))
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
    } finally {
      setForm((current) => ({ ...current, apiKey: "" }))
      connectMutation.reset()
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger render={<Button size="sm" variant="outline" />}>
        <PlusIcon data-icon="inline-start" />
        Add Connection
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Connect {provider.display_name}</DialogTitle>
          <DialogDescription>
            Give this connection a recognizable name, then enter the provider key. The key is stored
            securely and cannot be viewed again.
          </DialogDescription>
        </DialogHeader>
        <form
          id={`connect-${provider.provider_key}-api-key`}
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
              <FieldLabel htmlFor={`connection-label-${provider.provider_key}`}>
                Connection Name
              </FieldLabel>
              <Input
                aria-invalid={Boolean(fieldErrors["integration-connection-label"]) || undefined}
                id={`connection-label-${provider.provider_key}`}
                maxLength={120}
                onChange={(event) => {
                  setForm((current) => ({ ...current, label: event.currentTarget.value }))
                }}
                placeholder="Client account"
                value={form.label}
              />
              <FieldError>{fieldErrors["integration-connection-label"]}</FieldError>
            </Field>
            <Field data-invalid={Boolean(fieldErrors["integration-api-key"]) || undefined}>
              <FieldLabel htmlFor={`api-key-${provider.provider_key}`}>API Key</FieldLabel>
              <Input
                aria-invalid={Boolean(fieldErrors["integration-api-key"]) || undefined}
                autoComplete="off"
                id={`api-key-${provider.provider_key}`}
                onChange={(event) => {
                  setForm((current) => ({ ...current, apiKey: event.currentTarget.value }))
                }}
                type="password"
                value={form.apiKey}
              />
              <FieldDescription>
                <KeyRoundIcon className="mr-1 inline size-3.5" aria-hidden="true" />
                Required fields: {provider.required_form_fields.join(", ") || "API key"}.
              </FieldDescription>
              <FieldError>{fieldErrors["integration-api-key"]}</FieldError>
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
            form={`connect-${provider.provider_key}-api-key`}
            type="submit"
          >
            {connectMutation.isPending ? "Connecting" : "Connect"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
