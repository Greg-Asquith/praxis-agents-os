// apps/web/src/features/auth/components/profile-form.tsx

import { useState, type SyntheticEvent } from "react"
import { useSuspenseQuery } from "@tanstack/react-query"

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
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { currentUserQueryOptions } from "@/features/auth/api/get-current-user"
import { useUpdateCurrentUserMutation } from "@/features/auth/api/update-current-user"
import { getErrorMessage } from "@/lib/api/errors"
import { formString } from "@/lib/forms"

export function ProfileForm() {
  const { data: user } = useSuspenseQuery(currentUserQueryOptions())
  const updateMutation = useUpdateCurrentUserMutation()
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  function handleSubmit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setSaved(false)

    const formData = new FormData(event.currentTarget)
    const avatarUrl = formString(formData, "avatar_url").trim()

    updateMutation.mutate(
      {
        display_name: formString(formData, "display_name").trim() || null,
        avatar_url: avatarUrl.length > 0 ? avatarUrl : null,
      },
      {
        onSuccess: () => {
          setSaved(true)
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
        <CardTitle>Profile</CardTitle>
        <CardDescription>Update how you appear across Praxis.</CardDescription>
      </CardHeader>
      <form key={user.updated_at} onSubmit={handleSubmit}>
        <CardContent>
          <FieldGroup>
            {error && (
              <Alert variant="destructive">
                <AlertTitle>Profile not updated</AlertTitle>
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}
            {saved && (
              <Alert>
                <AlertTitle>Profile updated</AlertTitle>
                <AlertDescription>Your changes have been saved.</AlertDescription>
              </Alert>
            )}

            <Field>
              <FieldLabel htmlFor="profile-email">Email</FieldLabel>
              <Input id="profile-email" value={user.email} disabled readOnly />
              <FieldDescription>Email changes aren&apos;t available yet.</FieldDescription>
            </Field>

            <Field>
              <FieldLabel htmlFor="profile-display-name">Display name</FieldLabel>
              <Input
                defaultValue={user.display_name ?? ""}
                id="profile-display-name"
                name="display_name"
              />
            </Field>

            <Field>
              <FieldLabel htmlFor="profile-avatar-url">Avatar URL</FieldLabel>
              <Input
                defaultValue={user.avatar_url ?? ""}
                id="profile-avatar-url"
                name="avatar_url"
                type="url"
              />
            </Field>
          </FieldGroup>
        </CardContent>
        <CardFooter>
          <Button disabled={updateMutation.isPending} type="submit">
            {updateMutation.isPending ? "Saving" : "Save changes"}
          </Button>
        </CardFooter>
      </form>
    </Card>
  )
}
