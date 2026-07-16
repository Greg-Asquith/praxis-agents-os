// apps/web/src/features/auth/routes/oauth-link-callback-route.tsx

import { getRouteApi, useNavigate } from "@tanstack/react-router"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"

const routeApi = getRouteApi("/app/oauth/link/callback")

export function OAuthLinkCallbackRoute() {
  const navigate = useNavigate()
  const { error } = routeApi.useLoaderData()

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
      ) : null}
    </div>
  )
}
