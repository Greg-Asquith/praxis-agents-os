// apps/web/src/features/auth/routes/register-route.tsx

import { useState, type SyntheticEvent } from "react"
import { getRouteApi } from "@tanstack/react-router"
import { useQuery } from "@tanstack/react-query"
import { UserPlusIcon } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { useRegisterMutation } from "@/features/auth/api/register"
import { oauthProvidersQueryOptions } from "@/features/auth/api/get-oauth-providers"
import { AuthCard, AuthLink } from "@/features/auth/components/auth-card"
import { OAuthLoginProviders } from "@/features/auth/components/oauth-login-providers"
import { getErrorMessage } from "@/lib/api/errors"
import { formString } from "@/lib/forms"
import { authSuccessPath, invitationTokenFromRedirect } from "@/lib/safe-redirect"

const routeApi = getRouteApi("/auth/register")

export function RegisterRoute() {
  const { redirect } = routeApi.useSearch()
  const nextPath = authSuccessPath(redirect)
  const invitationToken = invitationTokenFromRedirect(nextPath)
  const registerMutation = useRegisterMutation()
  const providersQuery = useQuery(oauthProvidersQueryOptions())
  const [formError, setFormError] = useState<string | null>(null)
  const emailAuthEnabled =
    providersQuery.isError || providersQuery.data?.email_auth_enabled === true

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
        ...(invitationToken ? { invitation_token: invitationToken } : {}),
      },
      {
        onSuccess: () => {
          window.location.replace(nextPath)
        },
        onError: (error) => {
          setFormError(getErrorMessage(error))
        },
      }
    )
  }

  return (
    <AuthCard
      title="Create Account"
      description="Start with a personal workspace. You can add more later."
      footer={
        <span>
          Already have an account?{" "}
          <AuthLink to="/login" {...(redirect ? { redirect } : {})}>
            Sign In
          </AuthLink>
        </span>
      }
    >
      <div className="flex flex-col gap-6">
        <OAuthLoginProviders showSeparator={emailAuthEnabled} />

        <form hidden={!emailAuthEnabled} onSubmit={handleSubmit}>
          <FieldGroup>
            {invitationToken ? (
              <Alert>
                <AlertTitle>Workspace invitation</AlertTitle>
                <AlertDescription>You're joining via an invitation.</AlertDescription>
              </Alert>
            ) : null}
            {formError && (
              <Alert variant="destructive">
                <AlertTitle>Registration Failed</AlertTitle>
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

            <Button className="h-10 w-full" disabled={registerMutation.isPending} type="submit">
              <UserPlusIcon data-icon="inline-start" />
              {registerMutation.isPending ? "Creating Account" : "Create Account"}
            </Button>
          </FieldGroup>
        </form>
      </div>
    </AuthCard>
  )
}
