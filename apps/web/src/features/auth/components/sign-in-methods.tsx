// apps/web/src/features/auth/components/sign-in-methods.tsx

import { useState } from "react"
import { useQuery, useSuspenseQuery } from "@tanstack/react-query"
import { CheckIcon, KeyRoundIcon } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { identitiesQueryOptions } from "@/features/auth/api/get-identities"
import { oauthProvidersQueryOptions } from "@/features/auth/api/get-oauth-providers"
import {
  OAUTH_LINK_PROVIDER_STORAGE_KEY,
  useStartOauthLinkMutation,
} from "@/features/auth/api/oauth-link"
import { OAuthProviderIcon } from "@/features/auth/components/oauth-provider-icon"
import { useUnlinkOauthMutation } from "@/features/auth/api/unlink-oauth"
import { getErrorMessage } from "@/lib/api/errors"

function providerLabel(provider: string) {
  return provider.charAt(0).toUpperCase() + provider.slice(1)
}

export function SignInMethods() {
  const { data } = useSuspenseQuery(identitiesQueryOptions())
  const providersQuery = useQuery(oauthProvidersQueryOptions())
  const startLinkMutation = useStartOauthLinkMutation()
  const unlinkMutation = useUnlinkOauthMutation()
  const [error, setError] = useState<string | null>(null)
  const [pendingProvider, setPendingProvider] = useState<string | null>(null)

  const linkedProviders = new Set(data.identities.map((identity) => identity.provider))
  const connectable = (providersQuery.data?.providers ?? []).filter(
    (provider) => !linkedProviders.has(provider.name)
  )

  function handleConnect(provider: string) {
    setError(null)
    setPendingProvider(provider)
    startLinkMutation.mutate(provider, {
      onSuccess: (response) => {
        window.sessionStorage.setItem(OAUTH_LINK_PROVIDER_STORAGE_KEY, provider)
        window.location.assign(response.authorization_url)
      },
      onError: (mutationError) => {
        setPendingProvider(null)
        setError(getErrorMessage(mutationError))
      },
    })
  }

  function handleDisconnect(provider: string) {
    setError(null)
    if (!window.confirm(`Disconnect ${providerLabel(provider)} from your account?`)) {
      return
    }
    setPendingProvider(provider)
    unlinkMutation.mutate(provider, {
      onSettled: () => {
        setPendingProvider(null)
      },
      onError: (mutationError) => {
        setError(getErrorMessage(mutationError))
      },
    })
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Sign In Methods</CardTitle>
        <CardDescription>How you can sign in to your account.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {error && (
          <Alert variant="destructive">
            <AlertTitle>Couldn&apos;t update sign-in methods</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        <ul className="flex flex-col divide-y rounded-lg border">
          <li className="flex items-center justify-between gap-3 px-4 py-3">
            <span className="flex items-center gap-2 text-sm font-medium">
              <KeyRoundIcon className="size-4" />
              Password
            </span>
            {data.has_password ? (
              <Badge variant="secondary">
                <CheckIcon data-icon="inline-start" />
                Set
              </Badge>
            ) : (
              <Badge variant="outline">Not set</Badge>
            )}
          </li>

          {data.identities.map((identity) => (
            <li
              key={identity.provider}
              className="flex items-center justify-between gap-3 px-4 py-3"
            >
              <span className="flex min-w-0 flex-col gap-0.5">
                <span className="text-sm font-medium">{providerLabel(identity.provider)}</span>
                {identity.email && (
                  <span className="text-muted-foreground truncate text-xs">{identity.email}</span>
                )}
              </span>
              <span className="flex items-center gap-2">
                {identity.email_verified && (
                  <Badge variant="secondary">
                    <CheckIcon data-icon="inline-start" />
                    Verified
                  </Badge>
                )}
                <Button
                  disabled={pendingProvider === identity.provider}
                  onClick={() => {
                    handleDisconnect(identity.provider)
                  }}
                  size="sm"
                  variant="outline"
                >
                  Disconnect
                </Button>
              </span>
            </li>
          ))}
        </ul>

        {connectable.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {connectable.map((provider) => (
              <Button
                disabled={pendingProvider === provider.name}
                key={provider.name}
                onClick={() => {
                  handleConnect(provider.name)
                }}
                size="sm"
                variant="outline"
              >
                <OAuthProviderIcon provider={provider.icon || provider.name} />
                Connect {provider.display_name}
              </Button>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
