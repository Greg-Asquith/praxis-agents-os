// apps/web/src/features/files/components/folder-actions.tsx

import { useState } from "react"
import { MoreHorizontalIcon, PencilIcon, Trash2Icon } from "lucide-react"

import { useDeleteFolderMutation } from "../api/delete-folder"
import type { FileFolder } from "../types"
import { folderDeleteDescription } from "./folder-copy"
import { FolderDialog } from "./folder-dialog"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { getErrorMessage } from "@/lib/api/errors"

export function FolderActions({
  folder,
  onDeleted,
  triggerVariant = "ghost",
}: {
  folder: FileFolder
  onDeleted?: () => void
  triggerVariant?: "ghost" | "outline"
}) {
  const mutation = useDeleteFolderMutation()
  const [renameOpen, setRenameOpen] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  async function handleDelete() {
    setDeleteError(null)
    try {
      await mutation.mutateAsync(folder.id)
      setDeleteOpen(false)
      onDeleted?.()
    } catch (error) {
      setDeleteError(getErrorMessage(error))
    }
  }

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger
          render={
            <Button
              aria-label={`Actions for ${folder.name}`}
              size="icon-sm"
              variant={triggerVariant}
            />
          }
        >
          <MoreHorizontalIcon />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuGroup>
            <DropdownMenuItem
              onClick={() => {
                setRenameOpen(true)
              }}
            >
              <PencilIcon data-icon="inline-start" />
              Rename
            </DropdownMenuItem>
          </DropdownMenuGroup>
          <DropdownMenuSeparator />
          <DropdownMenuGroup>
            <DropdownMenuItem
              onClick={() => {
                setDeleteError(null)
                setDeleteOpen(true)
              }}
              variant="destructive"
            >
              <Trash2Icon data-icon="inline-start" />
              Delete
            </DropdownMenuItem>
          </DropdownMenuGroup>
        </DropdownMenuContent>
      </DropdownMenu>
      <FolderDialog folder={folder} open={renameOpen} onOpenChange={setRenameOpen} />
      <ConfirmDialog
        confirmIcon={<Trash2Icon data-icon="inline-start" />}
        confirmLabel="Delete Folder"
        confirmPendingLabel="Deleting"
        description={
          <>
            {folderDeleteDescription(folder)}
            {deleteError ? (
              <span className="text-destructive mt-2 block">{deleteError}</span>
            ) : null}
          </>
        }
        isPending={mutation.isPending}
        onConfirm={handleDelete}
        onOpenChange={(open) => {
          setDeleteOpen(open)
          if (!open) setDeleteError(null)
        }}
        open={deleteOpen}
        title="Delete folder?"
      />
    </>
  )
}
