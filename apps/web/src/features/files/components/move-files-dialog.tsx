// apps/web/src/features/files/components/move-files-dialog.tsx

import { useMemo, useState } from "react"
import { PlusIcon } from "lucide-react"

import { useMoveFilesMutation } from "../api/move-files"
import type { FileFolder } from "../types"
import { moveFilesDescription } from "./folder-copy"
import { FolderDialog } from "./folder-dialog"
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
import { Field, FieldLabel } from "@/components/ui/field"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { getErrorMessage } from "@/lib/api/errors"

const ROOT_VALUE = "__root__"

export function MoveFilesDialog({
  fileIds,
  folders,
  open,
  onMoved,
  onOpenChange,
}: {
  fileIds: string[]
  folders: FileFolder[]
  open: boolean
  onMoved?: (fileIds: string[]) => void
  onOpenChange: (open: boolean) => void
}) {
  const mutation = useMoveFilesMutation()
  const [destination, setDestination] = useState(ROOT_VALUE)
  const [error, setError] = useState<string | null>(null)
  const [createOpen, setCreateOpen] = useState(false)
  const [createdFolder, setCreatedFolder] = useState<FileFolder | null>(null)
  const destinations = useMemo(
    () =>
      createdFolder && !folders.some((folder) => folder.id === createdFolder.id)
        ? [...folders, createdFolder]
        : folders,
    [createdFolder, folders]
  )

  function handleOpenChange(nextOpen: boolean) {
    if (!nextOpen) {
      setDestination(ROOT_VALUE)
      setError(null)
      setCreatedFolder(null)
    }
    onOpenChange(nextOpen)
  }

  async function handleMove() {
    setError(null)
    try {
      await mutation.mutateAsync({
        fileIds,
        folderId: destination === ROOT_VALUE ? null : destination,
      })
      onMoved?.(fileIds)
      handleOpenChange(false)
    } catch (moveError) {
      setError(getErrorMessage(moveError))
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Move to Folder</DialogTitle>
          <DialogDescription>{moveFilesDescription(fileIds.length)}</DialogDescription>
        </DialogHeader>
        {error ? (
          <Alert variant="destructive">
            <AlertTitle>Files not moved</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        ) : null}
        <Field>
          <FieldLabel>Destination</FieldLabel>
          <Select
            value={destination}
            onValueChange={(value) => {
              setDestination(value ?? ROOT_VALUE)
            }}
          >
            <SelectTrigger className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ROOT_VALUE}>Root</SelectItem>
              {destinations.map((folder) => (
                <SelectItem key={folder.id} value={folder.id}>
                  {folder.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            onClick={() => {
              setCreateOpen(true)
            }}
            size="sm"
            type="button"
            variant="ghost"
          >
            <PlusIcon data-icon="inline-start" />
            New Folder
          </Button>
        </Field>
        <DialogFooter>
          <Button
            onClick={() => {
              handleOpenChange(false)
            }}
            type="button"
            variant="outline"
          >
            Cancel
          </Button>
          <Button
            disabled={mutation.isPending || fileIds.length === 0}
            onClick={() => void handleMove()}
            type="button"
          >
            {mutation.isPending ? "Moving" : "Move Files"}
          </Button>
        </DialogFooter>
        <FolderDialog
          open={createOpen}
          onOpenChange={setCreateOpen}
          onSaved={(folder) => {
            setCreatedFolder(folder)
            setDestination(folder.id)
          }}
        />
      </DialogContent>
    </Dialog>
  )
}
