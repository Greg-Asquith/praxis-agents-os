// apps/web/src/features/auth/components/profile-form.tsx

import { useState, type SyntheticEvent } from "react"
import { useSuspenseQuery } from "@tanstack/react-query"
import { Trash2Icon } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar"
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
import {
  useConfirmAvatarUploadMutation,
  useCreateAvatarUploadMutation,
  useDeleteAvatarMutation,
} from "@/features/auth/api/avatar"
import { currentUserQueryOptions } from "@/features/auth/api/get-current-user"
import { useUpdateCurrentUserMutation } from "@/features/auth/api/update-current-user"
import { uploadFileDirectly } from "@/lib/api/direct-upload"
import { getErrorMessage } from "@/lib/api/errors"
import { initials, normalizeOptionalText } from "@/lib/format"
import { formString } from "@/lib/forms"
import { appConfig } from "@/config/app"

export function ProfileForm() {
  const { data: user } = useSuspenseQuery(currentUserQueryOptions())
  const updateMutation = useUpdateCurrentUserMutation()
  const createAvatarUploadMutation = useCreateAvatarUploadMutation()
  const confirmAvatarUploadMutation = useConfirmAvatarUploadMutation()
  const deleteAvatarMutation = useDeleteAvatarMutation()
  const [avatarFile, setAvatarFile] = useState<File | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const isPending =
    updateMutation.isPending ||
    createAvatarUploadMutation.isPending ||
    confirmAvatarUploadMutation.isPending ||
    deleteAvatarMutation.isPending

  async function handleSubmit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setSaved(false)

    const formData = new FormData(event.currentTarget)

    try {
      await updateMutation.mutateAsync({
        display_name: normalizeOptionalText(formString(formData, "display_name")),
      })

      if (avatarFile) {
        const uploadGrant = await createAvatarUploadMutation.mutateAsync({
          content_type: avatarFile.type,
          filename: avatarFile.name || "avatar",
          size_bytes: avatarFile.size,
        })
        await uploadFileDirectly(uploadGrant.upload, avatarFile, uploadGrant.max_size_bytes)
        await confirmAvatarUploadMutation.mutateAsync(uploadGrant.upload_token)
        setAvatarFile(null)
      }

      setSaved(true)
    } catch (mutationError) {
      setError(getErrorMessage(mutationError))
    }
  }

  async function handleDeleteAvatar() {
    setError(null)
    setSaved(false)

    try {
      await deleteAvatarMutation.mutateAsync()
      setAvatarFile(null)
      setSaved(true)
    } catch (mutationError) {
      setError(getErrorMessage(mutationError))
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Profile</CardTitle>
        <CardDescription>Update how you appear across {appConfig.name}.</CardDescription>
      </CardHeader>
      <form
        key={user.updated_at}
        onSubmit={(event) => {
          void handleSubmit(event)
        }}
      >
        <CardContent>
          <FieldGroup>
            {error && (
              <Alert variant="destructive">
                <AlertTitle>Profile Not Updated</AlertTitle>
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}
            {saved && (
              <Alert>
                <AlertTitle>Profile Updated</AlertTitle>
                <AlertDescription>Your changes have been saved.</AlertDescription>
              </Alert>
            )}

            <Field>
              <FieldLabel htmlFor="profile-email">Email</FieldLabel>
              <Input id="profile-email" value={user.email} disabled readOnly />
              <FieldDescription>Your email address can&apos;t be changed.</FieldDescription>
            </Field>

            <Field>
              <FieldLabel htmlFor="profile-display-name">Display Name</FieldLabel>
              <Input
                defaultValue={user.display_name ?? ""}
                id="profile-display-name"
                name="display_name"
              />
            </Field>

            <Field>
              <FieldLabel htmlFor="profile-avatar-file">Avatar</FieldLabel>
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
                <Avatar size="lg" className="size-14">
                  {user.avatar_url && <AvatarImage src={user.avatar_url} />}
                  <AvatarFallback>{initials(user.display_name ?? user.email)}</AvatarFallback>
                </Avatar>
                <div className="flex min-w-0 flex-1 flex-col gap-1.5">
                  <Input
                    accept="image/jpeg,image/png,image/webp"
                    id="profile-avatar-file"
                    onChange={(event) => {
                      setAvatarFile(event.currentTarget.files?.[0] ?? null)
                    }}
                    type="file"
                  />
                  <FieldDescription>
                    {avatarFile ? avatarFile.name : "JPEG, PNG, or WebP."}
                  </FieldDescription>
                </div>
                {user.avatar_url && (
                  <Button
                    aria-label="Remove Avatar"
                    disabled={isPending}
                    onClick={() => {
                      void handleDeleteAvatar()
                    }}
                    size="icon"
                    type="button"
                    variant="outline"
                  >
                    <Trash2Icon />
                  </Button>
                )}
              </div>
            </Field>
          </FieldGroup>
        </CardContent>
        <CardFooter>
          <Button disabled={isPending} type="submit">
            {isPending ? "Saving" : "Save Changes"}
          </Button>
        </CardFooter>
      </form>
    </Card>
  )
}
