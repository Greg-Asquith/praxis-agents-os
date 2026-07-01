// apps/web/src/features/auth/components/oauth-login-providers.tsx

import { useEffect, useRef, useState } from "react"
import { useQuery } from "@tanstack/react-query"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { FieldSeparator } from "@/components/ui/field"
import { oauthProvidersQueryOptions } from "@/features/auth/api/get-oauth-providers"
import {
  OAUTH_LOGIN_PROVIDER_STORAGE_KEY,
  useStartOauthLoginMutation,
} from "@/features/auth/api/oauth-login"
import { OAuthProviderIcon } from "@/features/auth/components/oauth-provider-icon"
import { getErrorMessage } from "@/lib/api/errors"

const PENDING_FEEDBACK_DELAY_MS = 500

export function OAuthLoginProviders() {
  const providersQuery = useQuery(oauthProvidersQueryOptions())
  const startLoginMutation = useStartOauthLoginMutation()
  const startInFlightRef = useRef(false)
  const [error, setError] = useState<string | null>(null)
  const [pendingProvider, setPendingProvider] = useState<string | null>(null)
  const [showPendingFeedback, setShowPendingFeedback] = useState(false)

  const providers = providersQuery.data?.providers ?? []

  useEffect(() => {
    if (!pendingProvider || !startLoginMutation.isPending) {
      return
    }

    const timeoutId = window.setTimeout(() => {
      setShowPendingFeedback(true)
    }, PENDING_FEEDBACK_DELAY_MS)

    return () => {
      window.clearTimeout(timeoutId)
    }
  }, [pendingProvider, startLoginMutation.isPending])

  function handleStart(provider: string) {
    if (startInFlightRef.current) {
      return
    }

    startInFlightRef.current = true
    setError(null)
    setPendingProvider(provider)
    setShowPendingFeedback(false)

    startLoginMutation.mutate(provider, {
      onSuccess: (response) => {
        window.sessionStorage.setItem(OAUTH_LOGIN_PROVIDER_STORAGE_KEY, response.provider)
        window.location.assign(response.authorization_url)
      },
      onError: (mutationError) => {
        startInFlightRef.current = false
        window.sessionStorage.removeItem(OAUTH_LOGIN_PROVIDER_STORAGE_KEY)
        setPendingProvider(null)
        setShowPendingFeedback(false)
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
          const showOpeningState =
            showPendingFeedback && pendingProvider === provider.name && startLoginMutation.isPending
          return (
            <Button
              className="w-full"
              disabled={showPendingFeedback}
              key={provider.name}
              onClick={() => {
                handleStart(provider.name)
              }}
              type="button"
              variant="outline"
            >
              <OAuthProviderIcon provider={provider.icon || provider.name} />
              {showOpeningState
                ? `Opening ${provider.display_name}`
                : `Continue with ${provider.display_name}`}
            </Button>
          )
        })}
      </div>

      <FieldSeparator>or</FieldSeparator>
    </div>
  )
}
