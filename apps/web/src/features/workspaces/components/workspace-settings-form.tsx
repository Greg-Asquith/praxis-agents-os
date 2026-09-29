// apps/web/src/features/workspaces/components/workspace-settings-form.tsx

import { useState, type SyntheticEvent } from "react"
import { useQuery } from "@tanstack/react-query"
import { Trash2Icon } from "lucide-react"

import { ConfirmDialog } from "@/components/ui/confirm-dialog"
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
import {
  Field,
  FieldContent,
  FieldDescription,
  FieldGroup,
  FieldLabel,
} from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import { modelCatalogQueryOptions } from "@/features/models/api/list-model-catalog"
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
  const { data: modelCatalog } = useQuery(modelCatalogQueryOptions())
  const [iconSelection, setIconSelection] = useState<{
    file: File
    workspaceId: string
  } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const iconFile = iconSelection?.workspaceId === workspace.id ? iconSelection.file : null
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  const nextWorkspace = workspaces.find((item) => item.id !== workspace.id) ?? null

  const canManage =
    workspace.current_user_role === "owner" || workspace.current_user_role === "admin"
  const canDelete = workspace.current_user_role === "owner" && !workspace.is_personal
  const isSaving =
    updateWorkspaceMutation.isPending ||
    createIconUploadMutation.isPending ||
    confirmIconUploadMutation.isPending ||
    deleteIconMutation.isPending

  function handleDeleteRequest() {
    setError(null)
    if (!nextWorkspace) {
      setError("Create another workspace before deleting this one.")
      return
    }

    setDeleteDialogOpen(true)
  }

  async function handleSubmit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!canManage) return
    setError(null)

    const formData = new FormData(event.currentTarget)

    try {
      let updatedWorkspace = await updateWorkspaceMutation.mutateAsync({
        workspaceId: workspace.id,
        payload: {
          name: formString(formData, "name").trim(),
          ...defaultModelPayload(formString(formData, "default_model")),
          ...(!workspace.is_personal && {
            conversations_shared_by_default: formData.has("conversations_shared_by_default"),
          }),
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
    if (!nextWorkspace) {
      setError("Create another workspace before deleting this one.")
      setDeleteDialogOpen(false)
      return
    }

    deleteWorkspaceMutation.mutate(workspace.id, {
      onSuccess: () => {
        setDeleteDialogOpen(false)
        setWorkspaceBySlug(nextWorkspace.slug)
      },
      onError: (mutationError) => {
        setError(getErrorMessage(mutationError))
        setDeleteDialogOpen(false)
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
        <CardDescription>Manage the details for the active workspace.</CardDescription>
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
                    aria-label="Remove Workspace Icon"
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
            <Field>
              <FieldLabel htmlFor="settings-default-model">Default Large Language Model</FieldLabel>
              <Select
                defaultValue={
                  workspace.default_model_provider && workspace.default_model
                    ? `${workspace.default_model_provider}:${workspace.default_model}`
                    : PLATFORM_DEFAULT_MODEL
                }
                disabled={!canManage || !modelCatalog}
                name="default_model"
              >
                <SelectTrigger className="w-full sm:w-80" id="settings-default-model">
                  <SelectValue>
                    {(value: string) =>
                      value === PLATFORM_DEFAULT_MODEL
                        ? "Platform default"
                        : (modelCatalog?.models.find((model) => model.id === value)?.display_name ??
                          value)
                    }
                  </SelectValue>
                </SelectTrigger>
                <SelectContent align="start">
                  <SelectGroup>
                    <SelectItem value={PLATFORM_DEFAULT_MODEL}>Platform default</SelectItem>
                    {modelCatalog?.models
                      .filter((model) => model.supports_tools)
                      .map((model) => (
                        <SelectItem key={model.id} value={model.id}>
                          {model.display_name}
                        </SelectItem>
                      ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
              <FieldDescription>
                Agents that don't choose their own model use this one.
              </FieldDescription>
            </Field>
            {!workspace.is_personal && (
              <Field orientation="horizontal" data-disabled={!canManage}>
                <FieldContent>
                  <FieldLabel htmlFor="settings-default-sharing">
                    Conversations shared by default
                  </FieldLabel>
                  <FieldDescription id="settings-default-sharing-description">
                    New conversations in this workspace are shared with every member from the start.
                    Existing conversations are unchanged. Owners can still stop sharing a
                    conversation they own.
                  </FieldDescription>
                </FieldContent>
                <Switch
                  id="settings-default-sharing"
                  name="conversations_shared_by_default"
                  aria-describedby="settings-default-sharing-description"
                  defaultChecked={workspace.conversations_shared_by_default}
                  disabled={!canManage}
                />
              </Field>
            )}
          </FieldGroup>
        </CardContent>
        <CardFooter className="justify-between gap-3">
          <Button disabled={!canManage || isSaving} type="submit">
            {isSaving ? "Saving" : "Save Changes"}
          </Button>
          {canDelete && (
            <Button
              disabled={deleteWorkspaceMutation.isPending || isSaving}
              onClick={handleDeleteRequest}
              type="button"
              variant="destructive"
            >
              <Trash2Icon data-icon="inline-start" />
              Delete
            </Button>
          )}
        </CardFooter>
      </form>
      <ConfirmDialog
        confirmIcon={<Trash2Icon data-icon="inline-start" />}
        confirmLabel="Delete Workspace"
        confirmPendingLabel="Deleting"
        description={
          nextWorkspace
            ? `This removes ${workspace.name}. You will switch to ${nextWorkspace.name} afterward.`
            : "Create another workspace before deleting this one."
        }
        isPending={deleteWorkspaceMutation.isPending}
        onConfirm={handleDelete}
        onOpenChange={setDeleteDialogOpen}
        open={deleteDialogOpen}
        title="Delete workspace?"
      />
    </Card>
  )
}

const PLATFORM_DEFAULT_MODEL = "platform-default"

function defaultModelPayload(value: string) {
  if (!value) return {}
  if (value === PLATFORM_DEFAULT_MODEL) {
    return { default_model_provider: null, default_model: null }
  }
  const separator = value.indexOf(":")
  return {
    default_model_provider: value.slice(0, separator),
    default_model: value.slice(separator + 1),
  }
}
