// apps/web/src/features/files/components/folder-dialog.tsx

import { useState, type SyntheticEvent } from "react"

import { useCreateFolderMutation } from "../api/create-folder"
import { useUpdateFolderMutation } from "../api/update-folder"
import type { FileFolder } from "../types"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { getErrorMessage } from "@/lib/api/errors"
import { formString } from "@/lib/forms"

export function FolderDialog({
  folder = null,
  open,
  onOpenChange,
  onSaved,
}: {
  folder?: FileFolder | null
  open: boolean
  onOpenChange: (open: boolean) => void
  onSaved?: (folder: FileFolder) => void
}) {
  const createMutation = useCreateFolderMutation()
  const updateMutation = useUpdateFolderMutation()
  const [error, setError] = useState<string | null>(null)
  const isPending = createMutation.isPending || updateMutation.isPending

  function handleSubmit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    const name = formString(data, "name").trim()
    const description = formString(data, "description").trim() || null
    if (!name) {
      setError("Enter a folder name.")
      return
    }
    setError(null)
    const options = {
      onSuccess: (savedFolder: FileFolder) => {
        onSaved?.(savedFolder)
        onOpenChange(false)
      },
      onError: (mutationError: Error) => {
        setError(getErrorMessage(mutationError))
      },
    }
    if (folder) {
      updateMutation.mutate({ description, folderId: folder.id, name }, options)
    } else {
      createMutation.mutate({ description, name }, options)
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen) setError(null)
        onOpenChange(nextOpen)
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{folder ? "Rename Folder" : "New Folder"}</DialogTitle>
          <DialogDescription>
            {folder
              ? "Update the name or description. Files inside stay in this folder."
              : "Group files from the same piece of work so they are easier to find."}
          </DialogDescription>
        </DialogHeader>
        <form id="folder-form" onSubmit={handleSubmit}>
          <FieldGroup>
            {error ? (
              <Alert variant="destructive">
                <AlertTitle>Folder not saved</AlertTitle>
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            ) : null}
            <Field>
              <FieldLabel htmlFor="folder-name">Name</FieldLabel>
              <Input
                defaultValue={folder?.name ?? ""}
                id="folder-name"
                maxLength={255}
                name="name"
                required
              />
            </Field>
            <Field>
              <FieldLabel htmlFor="folder-description">Description</FieldLabel>
              <Textarea
                defaultValue={folder?.description ?? ""}
                id="folder-description"
                maxLength={4096}
                name="description"
                rows={3}
              />
            </Field>
          </FieldGroup>
        </form>
        <DialogFooter>
          <Button
            onClick={() => {
              onOpenChange(false)
            }}
            type="button"
            variant="outline"
          >
            Cancel
          </Button>
          <Button disabled={isPending} form="folder-form" type="submit">
            {isPending ? "Saving" : "Save Folder"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
