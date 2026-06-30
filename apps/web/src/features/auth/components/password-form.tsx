// apps/web/src/features/auth/components/password-form.tsx

import { useState, type SyntheticEvent } from "react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { useChangePasswordMutation } from "@/features/auth/api/change-password"
import { getErrorMessage } from "@/lib/api/errors"
import { formString } from "@/lib/forms"

export function PasswordForm() {
  const changePasswordMutation = useChangePasswordMutation()
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const [formKey, setFormKey] = useState(0)

  function handleSubmit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setSaved(false)

    const formData = new FormData(event.currentTarget)
    const newPassword = formString(formData, "new_password")
    const confirmPassword = formString(formData, "confirm_password")

    if (newPassword !== confirmPassword) {
      setError("New password and confirmation do not match.")
      return
    }

    changePasswordMutation.mutate(
      {
        current_password: formString(formData, "current_password"),
        new_password: newPassword,
      },
      {
        onSuccess: () => {
          setSaved(true)
          setFormKey((key) => key + 1)
        },
        onError: (mutationError) => {
          setError(getErrorMessage(mutationError))
        },
      }
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Password</CardTitle>
        <CardDescription>Change the password you use to sign in.</CardDescription>
      </CardHeader>
      <form key={formKey} onSubmit={handleSubmit}>
        <CardContent>
          <FieldGroup>
            {error && (
              <Alert variant="destructive">
                <AlertTitle>Password not changed</AlertTitle>
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}
            {saved && (
              <Alert>
                <AlertTitle>Password changed</AlertTitle>
                <AlertDescription>Use your new password next time you sign in.</AlertDescription>
              </Alert>
            )}

            <Field>
              <FieldLabel htmlFor="current-password">Current password</FieldLabel>
              <Input
                autoComplete="current-password"
                id="current-password"
                name="current_password"
                required
                type="password"
              />
            </Field>

            <Field>
              <FieldLabel htmlFor="new-password">New password</FieldLabel>
              <Input
                autoComplete="new-password"
                id="new-password"
                minLength={8}
                name="new_password"
                required
                type="password"
              />
            </Field>

            <Field>
              <FieldLabel htmlFor="confirm-password">Confirm new password</FieldLabel>
              <Input
                autoComplete="new-password"
                id="confirm-password"
                minLength={8}
                name="confirm_password"
                required
                type="password"
              />
            </Field>
          </FieldGroup>
        </CardContent>
        <CardFooter>
          <Button disabled={changePasswordMutation.isPending} type="submit">
            {changePasswordMutation.isPending ? "Updating" : "Update password"}
          </Button>
        </CardFooter>
      </form>
    </Card>
  )
}
