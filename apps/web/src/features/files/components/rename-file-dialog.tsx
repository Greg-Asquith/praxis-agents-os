// apps/web/src/features/files/components/rename-file-dialog.tsx

import { useState, type SyntheticEvent } from "react"

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
import { useUpdateFileMutation } from "@/features/files/api/update-file"
import type { WorkspaceFile } from "@/features/files/types"
import { getErrorMessage } from "@/lib/api/errors"
import { formString } from "@/lib/forms"

export function RenameFileDialog({
  file,
  onOpenChange,
}: {
  file: WorkspaceFile | null
  onOpenChange: (open: boolean) => void
}) {
  const updateMutation = useUpdateFileMutation()
  const [error, setError] = useState<string | null>(null)

  function handleSubmit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!file) {
      return
    }

    const formData = new FormData(event.currentTarget)
    const enteredName = formString(formData, "name").trim()
    const description = formString(formData, "description").trim()
    if (!enteredName) {
      setError("Enter a file name.")
      return
    }

    const name = `${withoutExtension(enteredName, file.extension)}${file.extension}`

    setError(null)
    updateMutation.mutate(
      { description: description || null, fileId: file.id, name },
      {
        onSuccess: () => {
          onOpenChange(false)
        },
        onError: (mutationError) => {
          setError(getErrorMessage(mutationError))
        },
      }
    )
  }

  return (
    <Dialog
      open={file !== null}
      onOpenChange={(open) => {
        if (!open) {
          setError(null)
        }
        onOpenChange(open)
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Rename File</DialogTitle>
          <DialogDescription>
            Choose a clear name and add an optional description for your team.
          </DialogDescription>
        </DialogHeader>
        {file ? (
          <form id="rename-file-form" onSubmit={handleSubmit}>
            <FieldGroup>
              {error ? (
                <Alert variant="destructive">
                  <AlertTitle>File not saved</AlertTitle>
                  <AlertDescription>{error}</AlertDescription>
                </Alert>
              ) : null}
              <Field>
                <FieldLabel htmlFor="rename-file-name">Name</FieldLabel>
                <div className="border-input bg-background focus-within:border-ring focus-within:ring-ring/50 flex rounded-md border shadow-xs focus-within:ring-[3px]">
                  <Input
                    className="min-w-0 flex-1 border-0 bg-transparent shadow-none focus-visible:ring-0"
                    defaultValue={withoutExtension(file.name, file.extension)}
                    id="rename-file-name"
                    maxLength={Math.max(1, 255 - file.extension.length)}
                    name="name"
                    required
                  />
                  <span className="text-muted-foreground flex items-center border-l px-3 text-sm">
                    {file.extension}
                  </span>
                </div>
              </Field>
              <Field>
                <FieldLabel htmlFor="rename-file-description">Description</FieldLabel>
                <Textarea
                  defaultValue={file.description ?? ""}
                  id="rename-file-description"
                  maxLength={4096}
                  name="description"
                  rows={3}
                />
              </Field>
            </FieldGroup>
          </form>
        ) : null}
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
          <Button disabled={updateMutation.isPending} form="rename-file-form" type="submit">
            {updateMutation.isPending ? "Saving" : "Save Changes"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function withoutExtension(name: string, extension: string) {
  return name.toLowerCase().endsWith(extension.toLowerCase())
    ? name.slice(0, Math.max(0, name.length - extension.length))
    : name
}
