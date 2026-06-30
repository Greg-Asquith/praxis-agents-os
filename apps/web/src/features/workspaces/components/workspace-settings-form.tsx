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
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { useDeleteWorkspaceMutation } from "@/features/workspaces/api/delete-workspace"
import { useUpdateWorkspaceMutation } from "@/features/workspaces/api/update-workspace"
import { useActiveWorkspace } from "@/features/workspaces/components/use-active-workspace"
import { getErrorMessage } from "@/lib/api/errors"
import { formString } from "@/lib/forms"

export function WorkspaceSettingsForm() {
  const { workspace, workspaces, setWorkspaceBySlug } = useActiveWorkspace()
  const updateWorkspaceMutation = useUpdateWorkspaceMutation()
  const deleteWorkspaceMutation = useDeleteWorkspaceMutation()
  const [error, setError] = useState<string | null>(null)

  const canManage =
    workspace.current_user_role === "owner" || workspace.current_user_role === "admin"
  const canDelete = workspace.current_user_role === "owner" && !workspace.is_personal

  function handleSubmit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)

    const formData = new FormData(event.currentTarget)
    const iconUrl = formString(formData, "icon_url").trim()

    updateWorkspaceMutation.mutate(
      {
        workspaceId: workspace.id,
        payload: {
          icon_url: iconUrl.length > 0 ? iconUrl : null,
          name: formString(formData, "name").trim(),
        },
      },
      {
        onSuccess: (updatedWorkspace) => {
          setWorkspaceBySlug(updatedWorkspace.slug)
        },
        onError: (mutationError) => {
          setError(getErrorMessage(mutationError))
        },
      }
    )
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

  return (
    <Card>
      <CardHeader>
        <CardTitle>Workspace details</CardTitle>
        <CardDescription>Update the name and icon for the active workspace.</CardDescription>
      </CardHeader>
      <form key={`${workspace.id}:${workspace.updated_at}`} onSubmit={handleSubmit}>
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
              <FieldLabel htmlFor="settings-icon">Icon URL</FieldLabel>
              <Input
                defaultValue={workspace.icon_url ?? ""}
                disabled={!canManage}
                id="settings-icon"
                name="icon_url"
                type="url"
              />
            </Field>
          </FieldGroup>
        </CardContent>
        <CardFooter className="justify-between gap-3">
          <Button disabled={!canManage || updateWorkspaceMutation.isPending} type="submit">
            {updateWorkspaceMutation.isPending ? "Saving" : "Save changes"}
          </Button>
          {canDelete && (
            <Button
              disabled={deleteWorkspaceMutation.isPending}
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
