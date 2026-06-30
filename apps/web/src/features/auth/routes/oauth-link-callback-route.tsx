// apps/web/src/features/auth/routes/oauth-link-callback-route.tsx

import { useEffect, useMemo, useRef, useState } from "react"
import { useNavigate } from "@tanstack/react-router"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import {
  OAUTH_LINK_PROVIDER_STORAGE_KEY,
  useCompleteOauthLinkMutation,
} from "@/features/auth/api/oauth-link"
import { getErrorMessage } from "@/lib/api/errors"

// Parse the callback params once, outside render, so the effect stays side-effect only.
function readCallback() {
  const params = new URLSearchParams(window.location.search)
  const provider = window.sessionStorage.getItem(OAUTH_LINK_PROVIDER_STORAGE_KEY)
  window.sessionStorage.removeItem(OAUTH_LINK_PROVIDER_STORAGE_KEY)
  return {
    code: params.get("code"),
    state: params.get("state"),
    providerError: params.get("error"),
    provider,
  }
}

export function OAuthLinkCallbackRoute() {
  const navigate = useNavigate()
  const { mutate: completeLink } = useCompleteOauthLinkMutation()
  const [callback] = useState(readCallback)
  const [mutationError, setMutationError] = useState<string | null>(null)
  const startedRef = useRef(false)

  const parsed = useMemo(() => {
    if (callback.providerError) {
      return { error: `The provider reported an error: ${callback.providerError}.`, ready: null }
    }
    if (!callback.provider || !callback.code || !callback.state) {
      return {
        error: "This sign-in link is missing required information. Please try connecting again.",
        ready: null,
      }
    }
    return {
      error: null,
      ready: { provider: callback.provider, code: callback.code, state: callback.state },
    }
  }, [callback])

  useEffect(() => {
    if (!parsed.ready || startedRef.current) {
      return
    }
    startedRef.current = true

    completeLink(parsed.ready, {
      onSuccess: () => {
        void navigate({ to: "/profile", replace: true })
      },
      onError: (error) => {
        setMutationError(getErrorMessage(error))
      },
    })
  }, [parsed, completeLink, navigate])

  const error = parsed.error ?? mutationError

  return (
    <div className="mx-auto flex w-full max-w-md flex-col gap-4 py-10">
      {error ? (
        <>
          <Alert variant="destructive">
            <AlertTitle>Couldn&apos;t connect provider</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
          <Button
            onClick={() => {
              void navigate({ to: "/profile", replace: true })
            }}
            variant="outline"
          >
            Back to profile settings
          </Button>
        </>
      ) : (
        <>
          <p className="text-muted-foreground text-sm">Connecting your account…</p>
          <Skeleton className="h-10 w-full" />
        </>
      )}
    </div>
  )
}
