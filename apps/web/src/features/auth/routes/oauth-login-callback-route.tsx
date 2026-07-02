// apps/web/src/features/auth/routes/oauth-login-callback-route.tsx

import { useEffect, useMemo, useRef, useState } from "react"
import { useNavigate } from "@tanstack/react-router"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import {
  OAUTH_LOGIN_PROVIDER_STORAGE_KEY,
  useCompleteOauthLoginMutation,
} from "@/features/auth/api/oauth-login"
import { AuthCard } from "@/features/auth/components/auth-card"
import {
  clearOauthCallbackProvider,
  readOauthCallback,
  type OAuthCallbackInput,
} from "@/features/auth/oauth-callback"
import { getErrorMessage } from "@/lib/api/errors"

import type { AuthResponse } from "@/features/auth/types"

const loginCompletionPromises = new Map<string, Promise<AuthResponse>>()

function loginCompletionKey(input: OAuthCallbackInput) {
  return `${input.provider}:${input.state}:${input.code}`
}

function completeLoginOnce(
  input: OAuthCallbackInput,
  completeLogin: (input: OAuthCallbackInput) => Promise<AuthResponse>
) {
  const key = loginCompletionKey(input)
  const existing = loginCompletionPromises.get(key)
  if (existing) {
    return existing
  }

  const promise = completeLogin(input)
  loginCompletionPromises.set(key, promise)
  return promise
}

export function OAuthLoginCallbackRoute() {
  const navigate = useNavigate()
  const { mutateAsync: completeLogin } = useCompleteOauthLoginMutation()
  const [callback] = useState(() => readOauthCallback(OAUTH_LOGIN_PROVIDER_STORAGE_KEY))
  const [mutationError, setMutationError] = useState<string | null>(null)
  const [twoFactorPending, setTwoFactorPending] = useState(false)
  const startedRef = useRef(false)

  const parsed = useMemo(() => {
    if (callback.providerError) {
      return { error: `The provider reported an error: ${callback.providerError}.`, ready: null }
    }
    if (!callback.provider || !callback.code || !callback.state) {
      return {
        error: "This sign-in link is missing required information. Please try signing in again.",
        ready: null,
      }
    }
    return {
      error: null,
      ready: { code: callback.code, provider: callback.provider, state: callback.state },
    }
  }, [callback])

  useEffect(() => {
    if (!parsed.ready || startedRef.current) {
      return
    }
    startedRef.current = true
    clearOauthCallbackProvider(OAUTH_LOGIN_PROVIDER_STORAGE_KEY)

    void completeLoginOnce(parsed.ready, completeLogin)
      .then((response) => {
        if (response.requires_twofa) {
          setTwoFactorPending(true)
          return
        }
        window.location.replace("/")
      })
      .catch((error: unknown) => {
        setMutationError(getErrorMessage(error))
      })
  }, [parsed, completeLogin])

  const error = parsed.error ?? mutationError

  return (
    <AuthCard
      title="Completing sign in"
      description="Finishing the provider sign-in flow."
      footer={
        <Button
          onClick={() => {
            void navigate({ to: "/login", replace: true })
          }}
          variant="link"
        >
          Back to Sign In
        </Button>
      }
    >
      {error ? (
        <Alert variant="destructive">
          <AlertTitle>Sign in failed</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : twoFactorPending ? (
        <Alert>
          <AlertTitle>Two-step verification required</AlertTitle>
          <AlertDescription>
            Your sign-in was accepted. Entering a verification code will be available with account
            security settings.
          </AlertDescription>
        </Alert>
      ) : (
        <div className="flex flex-col gap-3">
          <p className="text-muted-foreground text-sm">Completing sign in...</p>
          <Skeleton className="h-10 w-full" />
        </div>
      )}
    </AuthCard>
  )
}
