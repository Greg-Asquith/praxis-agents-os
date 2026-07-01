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
import { getErrorMessage } from "@/lib/api/errors"

function readCallback() {
  const params = new URLSearchParams(window.location.search)
  const provider = window.sessionStorage.getItem(OAUTH_LOGIN_PROVIDER_STORAGE_KEY)
  window.sessionStorage.removeItem(OAUTH_LOGIN_PROVIDER_STORAGE_KEY)
  return {
    code: params.get("code"),
    provider,
    providerError: params.get("error"),
    state: params.get("state"),
  }
}

export function OAuthLoginCallbackRoute() {
  const navigate = useNavigate()
  const { mutate: completeLogin } = useCompleteOauthLoginMutation()
  const [callback] = useState(readCallback)
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

    completeLogin(parsed.ready, {
      onSuccess: (response) => {
        if (response.requires_twofa) {
          setTwoFactorPending(true)
          return
        }
        void navigate({ to: "/", replace: true })
      },
      onError: (error) => {
        setMutationError(getErrorMessage(error))
      },
    })
  }, [parsed, completeLogin, navigate])

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
          Back to sign in
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
