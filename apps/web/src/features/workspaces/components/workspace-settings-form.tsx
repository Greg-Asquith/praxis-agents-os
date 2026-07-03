// apps/web/src/features/workspaces/components/workspace-settings-form.tsx

import { useState, type SyntheticEvent } from "react"
import { Trash2Icon } from "lucide-react"

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
import { useDeleteWorkspaceMutation } from "@/features/workspaces/api/delete-workspace"
import { useUpdateWorkspaceMutation } from "@/features/workspaces/api/update-workspace"
import {
  useConfirmWorkspaceIconUploadMutation,
  useCreateWorkspaceIconUploadMutation,
  useDeleteWorkspaceIconMutation,
} from "@/features/workspaces/api/workspace-icon"
import { useActiveWorkspace } from "@/features/workspaces/components/use-active-workspace"
import { WorkspaceIcon } from "@/features/workspaces/components/workspace-icon"
import { uploadFileDirectly } from "@/lib/api/direct-upload"
import { getErrorMessage } from "@/lib/api/errors"
import { formString } from "@/lib/forms"

export function WorkspaceSettingsForm() {
  const { workspace, workspaces, setWorkspaceBySlug } = useActiveWorkspace()
  const updateWorkspaceMutation = useUpdateWorkspaceMutation()
  const deleteWorkspaceMutation = useDeleteWorkspaceMutation()
  const createIconUploadMutation = useCreateWorkspaceIconUploadMutation()
  const confirmIconUploadMutation = useConfirmWorkspaceIconUploadMutation()
  const deleteIconMutation = useDeleteWorkspaceIconMutation()
  const [iconSelection, setIconSelection] = useState<{
    file: File
    workspaceId: string
  } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const iconFile = iconSelection?.workspaceId === workspace.id ? iconSelection.file : null

  const canManage =
    workspace.current_user_role === "owner" || workspace.current_user_role === "admin"
  const canDelete = workspace.current_user_role === "owner" && !workspace.is_personal
  const isSaving =
    updateWorkspaceMutation.isPending ||
    createIconUploadMutation.isPending ||
    confirmIconUploadMutation.isPending ||
    deleteIconMutation.isPending

  async function handleSubmit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)

    const formData = new FormData(event.currentTarget)

    try {
      let updatedWorkspace = await updateWorkspaceMutation.mutateAsync({
        workspaceId: workspace.id,
        payload: {
          name: formString(formData, "name").trim(),
        },
      })

      if (iconFile) {
        const uploadGrant = await createIconUploadMutation.mutateAsync({
          workspaceId: workspace.id,
          payload: {
            content_type: iconFile.type,
            filename: iconFile.name || "workspace-icon",
            size_bytes: iconFile.size,
          },
        })
        await uploadFileDirectly(uploadGrant.upload, iconFile, uploadGrant.max_size_bytes)
        updatedWorkspace = await confirmIconUploadMutation.mutateAsync({
          uploadToken: uploadGrant.upload_token,
          workspaceId: workspace.id,
        })
        setIconSelection(null)
      }

      setWorkspaceBySlug(updatedWorkspace.slug)
    } catch (mutationError) {
      setError(getErrorMessage(mutationError))
    }
  }

  function handleDelete() {
    const nextWorkspace = workspaces.find((item) => item.id !== workspace.id)
    if (!nextWorkspace) {
      setError("Create another workspace before deleting this one.")
      return
    }

    if (!window.confirm(`Delete ${workspace.name}?`)) {
      return
    }

    deleteWorkspaceMutation.mutate(workspace.id, {
      onSuccess: () => {
        setWorkspaceBySlug(nextWorkspace.slug)
      },
      onError: (mutationError) => {
        setError(getErrorMessage(mutationError))
      },
    })
  }

  async function handleDeleteIcon() {
    setError(null)

    try {
      const updatedWorkspace = await deleteIconMutation.mutateAsync(workspace.id)
      setIconSelection(null)
      setWorkspaceBySlug(updatedWorkspace.slug)
    } catch (mutationError) {
      setError(getErrorMessage(mutationError))
    }
  }

  return (
    <Card className="border-0! border-none! bg-transparent shadow-none ring-0">
      <CardHeader>
        <CardTitle>Workspace details</CardTitle>
        <CardDescription>Update the name and icon for the active workspace.</CardDescription>
      </CardHeader>
      <form
        key={`${workspace.id}:${workspace.updated_at}`}
        onSubmit={(event) => {
          void handleSubmit(event)
        }}
      >
        <CardContent>
          <FieldGroup>
            {error && (
              <Alert variant="destructive">
                <AlertTitle>Workspace not updated</AlertTitle>
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}

            <Field>
              <FieldLabel htmlFor="settings-name">Name</FieldLabel>
              <Input
                defaultValue={workspace.name}
                disabled={!canManage}
                id="settings-name"
                name="name"
                required
              />
            </Field>

            <Field>
              <FieldLabel htmlFor="settings-icon-file">Icon</FieldLabel>
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
                <WorkspaceIcon size="lg" workspace={workspace} />
                <div className="flex min-w-0 flex-1 flex-col gap-1.5">
                  <Input
                    accept="image/jpeg,image/png,image/webp"
                    disabled={!canManage}
                    id="settings-icon-file"
                    onChange={(event) => {
                      const file = event.currentTarget.files?.[0] ?? null
                      setIconSelection(file ? { file, workspaceId: workspace.id } : null)
                    }}
                    type="file"
                  />
                  <FieldDescription>
                    {iconFile ? iconFile.name : "JPEG, PNG, or WebP."}
                  </FieldDescription>
                </div>
                {workspace.icon_url && (
                  <Button
                    aria-label="Remove workspace icon"
                    disabled={!canManage || isSaving}
                    onClick={() => {
                      void handleDeleteIcon()
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
        <CardFooter className="justify-between gap-3">
          <Button disabled={!canManage || isSaving} type="submit">
            {isSaving ? "Saving" : "Save changes"}
          </Button>
          {canDelete && (
            <Button
              disabled={deleteWorkspaceMutation.isPending || isSaving}
              onClick={handleDelete}
              type="button"
              variant="destructive"
            >
              <Trash2Icon data-icon="inline-start" />
              Delete
            </Button>
          )}
        </CardFooter>
      </form>
    </Card>
  )
}
