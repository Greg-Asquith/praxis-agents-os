// apps/web/src/features/auth/routes/login-route.tsx

import { useState, type SyntheticEvent } from "react"
import { useNavigate } from "@tanstack/react-router"
import { LogInIcon } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Field, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { useLoginMutation } from "@/features/auth/api/login"
import { AuthCard, AuthLink } from "@/features/auth/components/auth-card"
import { OAuthLoginProviders } from "@/features/auth/components/oauth-login-providers"
import { TwoFactorVerificationForm } from "@/features/auth/components/two-factor-verification-form"
import { getErrorMessage } from "@/lib/api/errors"
import { formString } from "@/lib/forms"

export function LoginRoute() {
  const navigate = useNavigate()
  const loginMutation = useLoginMutation()
  const [formError, setFormError] = useState<string | null>(null)
  const [twoFactorPending, setTwoFactorPending] = useState(false)

  function handleSubmit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault()
    setFormError(null)
    setTwoFactorPending(false)

    const formData = new FormData(event.currentTarget)
    const email = formString(formData, "email")
    const password = formString(formData, "password")

    loginMutation.mutate(
      { email, password },
      {
        onSuccess: (response) => {
          if (response.requires_twofa) {
            setTwoFactorPending(true)
            return
          }
          void navigate({ to: "/" })
        },
        onError: (error) => {
          setFormError(getErrorMessage(error))
        },
      }
    )
  }

  return (
    <AuthCard
      title={twoFactorPending ? "Two-Step Verification" : "Sign In"}
      description={
        twoFactorPending
          ? "Confirm this sign-in with your authenticator."
          : "Use your Praxis account to continue."
      }
      footer={
        twoFactorPending ? (
          <Button
            onClick={() => {
              setTwoFactorPending(false)
            }}
            variant="link"
          >
            Back to Sign In
          </Button>
        ) : (
          <span>
            <AuthLink to="/register">Create a New Account</AuthLink>
          </span>
        )
      }
    >
      {twoFactorPending ? (
        <TwoFactorVerificationForm
          onVerified={() => {
            window.location.replace("/")
          }}
        />
      ) : (
        <div className="flex flex-col gap-6">
          <OAuthLoginProviders />

          <form onSubmit={handleSubmit}>
            <FieldGroup>
              {formError && (
                <Alert variant="destructive">
                  <AlertTitle>Sign In Failed</AlertTitle>
                  <AlertDescription>{formError}</AlertDescription>
                </Alert>
              )}

              <Field>
                <FieldLabel htmlFor="email">Email</FieldLabel>
                <Input
                  autoComplete="email"
                  id="email"
                  name="email"
                  placeholder="you@example.com"
                  required
                  type="email"
                />
              </Field>

              <Field>
                <FieldLabel htmlFor="password">Password</FieldLabel>
                <Input
                  autoComplete="current-password"
                  id="password"
                  name="password"
                  required
                  type="password"
                />
              </Field>

              <Field>
                <Button className="h-10 w-full" disabled={loginMutation.isPending} type="submit">
                  <LogInIcon data-icon="inline-start" />
                  {loginMutation.isPending ? "Signing In" : "Sign In"}
                </Button>
                <FieldError />
              </Field>
            </FieldGroup>
          </form>
        </div>
      )}
    </AuthCard>
  )
}
