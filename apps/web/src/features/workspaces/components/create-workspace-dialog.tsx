// apps/web/src/features/workspaces/components/create-workspace-dialog.tsx

import { useState, type SyntheticEvent } from "react"
import { PlusIcon } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { useCreateWorkspaceMutation } from "@/features/workspaces/api/create-workspace"
import { useActiveWorkspace } from "@/features/workspaces/components/use-active-workspace"
import { getErrorMessage } from "@/lib/api/errors"
import { formString } from "@/lib/forms"

export function CreateWorkspaceDialog() {
  const { setWorkspaceBySlug } = useActiveWorkspace()
  const createWorkspaceMutation = useCreateWorkspaceMutation()
  const [open, setOpen] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function handleSubmit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)

    const formData = new FormData(event.currentTarget)

    createWorkspaceMutation.mutate(
      {
        name: formString(formData, "name"),
      },
      {
        onSuccess: (workspace) => {
          setWorkspaceBySlug(workspace.slug)
          setOpen(false)
        },
        onError: (mutationError) => {
          setError(getErrorMessage(mutationError))
        },
      }
    )
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger render={<Button />}>
        <PlusIcon data-icon="inline-start" />
        New workspace
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New workspace</DialogTitle>
          <DialogDescription>
            Create a shared workspace for a team, client, or environment.
          </DialogDescription>
        </DialogHeader>
        <form id="create-workspace-form" onSubmit={handleSubmit}>
          <FieldGroup>
            {error && (
              <Alert variant="destructive">
                <AlertTitle>Workspace not created</AlertTitle>
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}
            <Field>
              <FieldLabel htmlFor="workspace-name">Name</FieldLabel>
              <Input id="workspace-name" name="name" required />
            </Field>
          </FieldGroup>
        </form>
        <DialogFooter>
          <Button
            variant="outline"
            type="button"
            onClick={() => {
              setOpen(false)
            }}
          >
            Cancel
          </Button>
          <Button
            disabled={createWorkspaceMutation.isPending}
            form="create-workspace-form"
            type="submit"
          >
            {createWorkspaceMutation.isPending ? "Creating" : "Create"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
