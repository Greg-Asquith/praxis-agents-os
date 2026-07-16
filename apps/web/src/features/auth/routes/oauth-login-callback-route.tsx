// apps/web/src/features/auth/routes/oauth-login-callback-route.tsx

import { getRouteApi, useNavigate } from "@tanstack/react-router"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { AuthCard } from "@/features/auth/components/auth-card"

const routeApi = getRouteApi("/auth/oauth/callback")

export function OAuthLoginCallbackRoute() {
  const navigate = useNavigate()
  const { error, twoFactorPending } = routeApi.useLoaderData()

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
      ) : null}
    </AuthCard>
  )
}
