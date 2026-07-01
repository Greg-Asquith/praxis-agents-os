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
      title="Sign in"
      description="Use your Praxis account to continue."
      footer={
        <span>
          <AuthLink to="/register">Create a New Account</AuthLink>
        </span>
      }
    >
      <div className="flex flex-col gap-5">
        <OAuthLoginProviders />

        <form onSubmit={handleSubmit}>
          <FieldGroup>
            {formError && (
              <Alert variant="destructive">
                <AlertTitle>Sign in failed</AlertTitle>
                <AlertDescription>{formError}</AlertDescription>
              </Alert>
            )}

            {twoFactorPending && (
              <Alert>
                <AlertTitle>Two-step verification required</AlertTitle>
                <AlertDescription>
                  Your password was accepted. Entering a verification code will be available with
                  account security settings.
                </AlertDescription>
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
              <Button className="w-full" disabled={loginMutation.isPending} type="submit">
                <LogInIcon data-icon="inline-start" />
                {loginMutation.isPending ? "Signing in" : "Sign in"}
              </Button>
              <FieldError />
            </Field>
          </FieldGroup>
        </form>
      </div>
    </AuthCard>
  )
}
