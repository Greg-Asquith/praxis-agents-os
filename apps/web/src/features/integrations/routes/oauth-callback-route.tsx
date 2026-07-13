// apps/web/src/features/integrations/routes/oauth-callback-route.tsx

import { useEffect, useRef, useState } from "react"
import { useNavigate } from "@tanstack/react-router"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import {
  type CompleteIntegrationOAuthInput,
  useCompleteIntegrationOAuthMutation,
} from "@/features/integrations/api/complete-oauth-callback"
import type { OAuthCallbackResponse } from "@/features/integrations/types"
import { getErrorMessage } from "@/lib/api/errors"

const completionPromises = new Map<string, Promise<OAuthCallbackResponse>>()

function readCallback(): CompleteIntegrationOAuthInput | null {
  const search = new URLSearchParams(window.location.search)
  const state = search.get("state")
  if (!state) {
    return null
  }
  return {
    code: search.get("code"),
    error: search.get("error"),
    state,
  }
}

function completeOnce(
  input: CompleteIntegrationOAuthInput,
  complete: (value: CompleteIntegrationOAuthInput) => Promise<OAuthCallbackResponse>
) {
  const key = `${input.state}:${input.code ?? ""}:${input.error ?? ""}`
  const existing = completionPromises.get(key)
  if (existing) {
    return existing
  }
  const promise = complete(input)
  completionPromises.set(key, promise)
  return promise
}

export function IntegrationOAuthCallbackRoute() {
  const navigate = useNavigate()
  const { mutateAsync: complete } = useCompleteIntegrationOAuthMutation()
  const [callback] = useState(readCallback)
  const [mutationError, setMutationError] = useState<string | null>(null)
  const startedRef = useRef(false)

  useEffect(() => {
    if (!callback || startedRef.current) {
      return
    }
    startedRef.current = true
    void completeOnce(callback, complete)
      .then((response) => {
        window.location.replace(response.next_path ?? "/")
      })
      .catch((error: unknown) => {
        setMutationError(getErrorMessage(error))
      })
  }, [callback, complete])

  const error = callback ? mutationError : "This connection link is missing its OAuth state."

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
              void navigate({ to: "/", replace: true })
            }}
            variant="outline"
          >
            Back to home
          </Button>
        </>
      ) : (
        <>
          <p className="text-muted-foreground text-sm">Connecting your integration…</p>
          <Skeleton className="h-10 w-full" />
        </>
      )}
    </div>
  )
}
