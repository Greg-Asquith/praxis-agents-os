// apps/web/src/features/auth/routes/oauth-callback-route.tsx

import { getRouteApi, useNavigate } from "@tanstack/react-router"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { AuthCard } from "@/features/auth/components/auth-card"
import { TwoFactorVerificationForm } from "@/features/auth/components/two-factor-verification-form"

const routeApi = getRouteApi("/oauth-callback/oauth/callback")

export function OAuthCallbackRoute() {
  const result = routeApi.useLoaderData()

  return result.flow === "link" ? (
    <OAuthLinkCallback error={result.error} />
  ) : (
    <OAuthLoginCallback
      error={result.error}
      nextPath={result.nextPath}
      twoFactorPending={result.twoFactorPending}
    />
  )
}

function OAuthLinkCallback({ error }: { error: string | null }) {
  const navigate = useNavigate()

  return (
    <AuthCard
      title="Connecting Sign-In Method"
      description="Finishing the provider connection."
      footer={
        <Button
          onClick={() => {
            void navigate({ to: "/profile", replace: true })
          }}
          variant="link"
        >
          Back to Profile Settings
        </Button>
      }
    >
      {error ? (
        <Alert variant="destructive">
          <AlertTitle>Couldn&apos;t Connect Provider</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}
    </AuthCard>
  )
}

function OAuthLoginCallback({
  error,
  nextPath,
  twoFactorPending,
}: {
  error: string | null
  nextPath: string | null
  twoFactorPending: boolean
}) {
  const navigate = useNavigate()

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
