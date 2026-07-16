// apps/web/src/features/integrations/routes/oauth-callback-route.tsx

import { getRouteApi, useNavigate } from "@tanstack/react-router"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"

const routeApi = getRouteApi("/app/integrations/oauth/callback")

export function IntegrationOAuthCallbackRoute() {
  const navigate = useNavigate()
  const { error } = routeApi.useLoaderData()

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
            Back to Home
          </Button>
        </>
      ) : null}
    </div>
  )
}
