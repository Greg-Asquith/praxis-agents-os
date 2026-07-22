// apps/web/src/features/integrations/components/connect-oauth-button.tsx

import { useState, type SyntheticEvent } from "react"
import { ExternalLinkIcon } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Field, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { useStartOAuthMutation } from "@/features/integrations/api/start-oauth"
import type { IntegrationProvider } from "@/features/integrations/types"
import { getErrorMessage } from "@/lib/api/errors"

type ConnectOAuthButtonProps = {
  connectionId: string
  connectionLabel: string
  provider: IntegrationProvider
}

export function ConnectOAuthButton({
  connectionId,
  connectionLabel,
  provider,
}: ConnectOAuthButtonProps) {
  return (
    <OAuthRedirectButton connectionId={connectionId} label={connectionLabel} provider={provider} />
  )
}

function OAuthRedirectButton({
  connectionId,
  label,
  provider,
}: {
  connectionId: string
  label: string
  provider: IntegrationProvider
}) {
  const mutation = useStartOAuthMutation()
  const [error, setError] = useState<string | null>(null)

  async function start() {
    setError(null)
    try {
      const response = await mutation.mutateAsync({
        connection_id: connectionId,
        label,
        next_path: integrationDetailReturnPath(provider.provider_key),
        owner_scope: provider.owner_scope,
        provider_key: provider.provider_key,
      })
      window.location.assign(response.authorization_url)
    } catch (mutationError) {
      setError(getErrorMessage(mutationError))
    }
  }

  return (
    <div className="flex flex-col items-start gap-2">
      <Button disabled={mutation.isPending} onClick={() => void start()} size="sm" type="button">
        <ExternalLinkIcon data-icon="inline-start" />
        {mutation.isPending ? "Opening Provider" : "Sign In Again"}
      </Button>
      {error ? <p className="text-destructive text-xs">{error}</p> : null}
    </div>
  )
}

export function OAuthConnectionForm({
  onCancel,
  provider,
}: {
  onCancel: () => void
  provider: IntegrationProvider
}) {
  const mutation = useStartOAuthMutation()
  const [label, setLabel] = useState("")
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault()
    const connectionLabel = label.trim()
    if (!connectionLabel) {
      setError("Enter a name that identifies this connection.")
      return
    }
    setError(null)
    try {
      const response = await mutation.mutateAsync({
        label: connectionLabel,
        next_path: integrationDetailReturnPath(provider.provider_key),
        owner_scope: provider.owner_scope,
        provider_key: provider.provider_key,
      })
      window.location.assign(response.authorization_url)
    } catch (mutationError) {
      setError(getErrorMessage(mutationError))
    }
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>Connect {provider.display_name}</DialogTitle>
        <DialogDescription>
          Name this account before continuing to the provider to sign in.
        </DialogDescription>
      </DialogHeader>
      <form
        id={`connect-${provider.provider_key}-oauth`}
        onSubmit={(event) => {
          void handleSubmit(event)
        }}
      >
        <FieldGroup>
          {error ? (
            <Alert variant="destructive">
              <AlertTitle>Connection not started</AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          ) : null}
          <Field data-invalid={Boolean(error) || undefined}>
            <FieldLabel htmlFor={`oauth-label-${provider.provider_key}`}>
              Connection Name
            </FieldLabel>
            <Input
              aria-invalid={Boolean(error) || undefined}
              id={`oauth-label-${provider.provider_key}`}
              maxLength={120}
              onChange={(event) => {
                setLabel(event.currentTarget.value)
                setError(null)
              }}
              placeholder="Client account"
              value={label}
            />
            <FieldError>{error}</FieldError>
          </Field>
        </FieldGroup>
      </form>
      <DialogFooter>
        <Button onClick={onCancel} type="button" variant="outline">
          Cancel
        </Button>
        <Button
          disabled={mutation.isPending}
          form={`connect-${provider.provider_key}-oauth`}
          type="submit"
        >
          <ExternalLinkIcon data-icon="inline-start" />
          {mutation.isPending ? "Opening Provider" : "Continue"}
        </Button>
      </DialogFooter>
    </>
  )
}

function integrationDetailReturnPath(providerKey: string) {
  return `/integrations/${encodeURIComponent(providerKey)}?integration_status=connected`
}
