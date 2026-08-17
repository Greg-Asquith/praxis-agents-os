// apps/web/src/features/auth/routes/oauth-login-callback-route.tsx

import { getRouteApi, useNavigate } from "@tanstack/react-router"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { AuthCard } from "@/features/auth/components/auth-card"
import { TwoFactorVerificationForm } from "@/features/auth/components/two-factor-verification-form"

const routeApi = getRouteApi("/auth/oauth/callback")

export function OAuthLoginCallbackRoute() {
  const navigate = useNavigate()
  const { error, nextPath, twoFactorPending } = routeApi.useLoaderData()

  return (
    <AuthCard
      title={twoFactorPending ? "Two-Step Verification" : "Completing Sign In"}
      description={
        twoFactorPending
          ? "Confirm this sign-in with your authenticator."
          : "Finishing the provider sign-in flow."
      }
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
          <AlertTitle>Sign In Failed</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : twoFactorPending ? (
        <TwoFactorVerificationForm
          onVerified={() => {
            window.location.replace(nextPath ?? "/")
          }}
        />
      ) : null}
    </AuthCard>
  )
}
