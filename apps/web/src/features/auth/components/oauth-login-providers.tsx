// apps/web/src/features/auth/components/oauth-login-providers.tsx

import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { LogInIcon } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { FieldSeparator } from "@/components/ui/field"
import { oauthProvidersQueryOptions } from "@/features/auth/api/get-oauth-providers"
import {
  OAUTH_LOGIN_PROVIDER_STORAGE_KEY,
  useStartOauthLoginMutation,
} from "@/features/auth/api/oauth-login"
import { getErrorMessage } from "@/lib/api/errors"

export function OAuthLoginProviders() {
  const providersQuery = useQuery(oauthProvidersQueryOptions())
  const startLoginMutation = useStartOauthLoginMutation()
  const [error, setError] = useState<string | null>(null)
  const [pendingProvider, setPendingProvider] = useState<string | null>(null)

  const providers = providersQuery.data?.providers ?? []

  function handleStart(provider: string) {
    setError(null)
    setPendingProvider(provider)
    window.sessionStorage.setItem(OAUTH_LOGIN_PROVIDER_STORAGE_KEY, provider)

    startLoginMutation.mutate(provider, {
      onSuccess: (response) => {
        window.location.assign(response.authorization_url)
      },
      onError: (mutationError) => {
        window.sessionStorage.removeItem(OAUTH_LOGIN_PROVIDER_STORAGE_KEY)
        setPendingProvider(null)
        setError(getErrorMessage(mutationError))
      },
    })
  }

  if (providers.length === 0) {
    return null
  }

  return (
    <div className="flex flex-col gap-4">
      {error && (
        <Alert variant="destructive">
          <AlertTitle>Provider sign in failed</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <div className="grid gap-2">
        {providers.map((provider) => {
          const isPending = pendingProvider === provider.name && startLoginMutation.isPending
          return (
            <Button
              className="w-full"
              disabled={startLoginMutation.isPending}
              key={provider.name}
              onClick={() => {
                handleStart(provider.name)
              }}
              type="button"
              variant="outline"
            >
              <LogInIcon data-icon="inline-start" />
              {isPending ? `Opening ${provider.display_name}` : `Continue with ${provider.display_name}`}
            </Button>
          )
        })}
      </div>

      <FieldSeparator>or</FieldSeparator>
    </div>
  )
}
