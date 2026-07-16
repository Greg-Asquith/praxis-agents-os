// apps/web/src/features/auth/routes/register-route.tsx

import { useState, type SyntheticEvent } from "react"
import { useNavigate } from "@tanstack/react-router"
import { UserPlusIcon } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { useRegisterMutation } from "@/features/auth/api/register"
import { AuthCard, AuthLink } from "@/features/auth/components/auth-card"
import { OAuthLoginProviders } from "@/features/auth/components/oauth-login-providers"
import { getErrorMessage } from "@/lib/api/errors"
import { formString } from "@/lib/forms"

export function RegisterRoute() {
  const navigate = useNavigate()
  const registerMutation = useRegisterMutation()
  const [formError, setFormError] = useState<string | null>(null)

  function handleSubmit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault()
    setFormError(null)

    const formData = new FormData(event.currentTarget)
    const displayName = formString(formData, "display_name").trim()

    registerMutation.mutate(
      {
        display_name: displayName.length > 0 ? displayName : null,
        email: formString(formData, "email"),
        password: formString(formData, "password"),
      },
      {
        onSuccess: () => {
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
      title="Create account"
      description="Start with a personal workspace. You can add more later."
      footer={
        <span>
          Already have an account? <AuthLink to="/login">Sign In</AuthLink>
        </span>
      }
    >
      <div className="flex flex-col gap-5">
        <OAuthLoginProviders />

        <form onSubmit={handleSubmit}>
          <FieldGroup>
            {formError && (
              <Alert variant="destructive">
                <AlertTitle>Registration failed</AlertTitle>
                <AlertDescription>{formError}</AlertDescription>
              </Alert>
            )}

            <Field>
              <FieldLabel htmlFor="display_name">Name</FieldLabel>
              <Input
                autoComplete="name"
                id="display_name"
                name="display_name"
                placeholder="Ada Lovelace"
              />
            </Field>

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
                autoComplete="new-password"
                id="password"
                minLength={8}
                name="password"
                required
                type="password"
              />
              <FieldDescription>Use at least 8 characters.</FieldDescription>
            </Field>

            <Button className="w-full" disabled={registerMutation.isPending} type="submit">
              <UserPlusIcon data-icon="inline-start" />
              {registerMutation.isPending ? "Creating Account" : "Create Account"}
            </Button>
          </FieldGroup>
        </form>
      </div>
    </AuthCard>
  )
}
