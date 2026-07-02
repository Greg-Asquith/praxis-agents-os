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
import {
  clearOauthCallbackProvider,
  readOauthCallback,
  type OAuthCallbackInput,
} from "@/features/auth/oauth-callback"
import { getErrorMessage } from "@/lib/api/errors"

import type { IdentitiesResponse } from "@/features/auth/types"

const linkCompletionPromises = new Map<string, Promise<IdentitiesResponse>>()

function linkCompletionKey(input: OAuthCallbackInput) {
  return `${input.provider}:${input.state}:${input.code}`
}

function completeLinkOnce(
  input: OAuthCallbackInput,
  completeLink: (input: OAuthCallbackInput) => Promise<IdentitiesResponse>
) {
  const key = linkCompletionKey(input)
  const existing = linkCompletionPromises.get(key)
  if (existing) {
    return existing
  }

  const promise = completeLink(input)
  linkCompletionPromises.set(key, promise)
  return promise
}

export function OAuthLinkCallbackRoute() {
  const navigate = useNavigate()
  const { mutateAsync: completeLink } = useCompleteOauthLinkMutation()
  const [callback] = useState(() => readOauthCallback(OAUTH_LINK_PROVIDER_STORAGE_KEY))
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
    clearOauthCallbackProvider(OAUTH_LINK_PROVIDER_STORAGE_KEY)

    void completeLinkOnce(parsed.ready, completeLink)
      .then(() => {
        window.location.replace("/profile")
      })
      .catch((error: unknown) => {
        setMutationError(getErrorMessage(error))
      })
  }, [parsed, completeLink])

  const error = parsed.error ?? mutationError

  return (
    <div className="mx-auto flex w-full max-w-md flex-col gap-4 py-10">
      {error ? (
        <>
          <Alert variant="destructive">
            <AlertTitle>Couldn&apos;t Connect Provider</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
          <Button
            onClick={() => {
              void navigate({ to: "/profile", replace: true })
            }}
            variant="outline"
          >
            Back to Profile Settings
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
