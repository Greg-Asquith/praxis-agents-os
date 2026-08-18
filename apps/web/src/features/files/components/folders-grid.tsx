// apps/web/src/features/files/components/folders-grid.tsx

import { useState } from "react"
import { FolderIcon, PlusIcon } from "lucide-react"

import type { FileFolder } from "../types"
import { FolderActions } from "./folder-actions"
import { FolderDialog } from "./folder-dialog"
import { Button } from "@/components/ui/button"
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { formatBytes, relativeDateTime } from "@/lib/format"

export function FoldersGrid({
  folders,
  onOpenFolder,
}: {
  folders: FileFolder[]
  onOpenFolder: (folderId: string) => void
}) {
  return (
    <section aria-label="Folders" className="flex flex-col gap-3">
      {folders.length > 0 ? (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {folders.map((folder) => (
            <Card
              className="hover:ring-primary/35 relative transition-colors"
              key={folder.id}
              size="sm"
            >
              <button
                aria-label={`Open folder ${folder.name}`}
                className="focus-visible:ring-ring absolute inset-0 rounded-xl outline-none hover:cursor-pointer focus-visible:ring-2"
                onClick={() => {
                  onOpenFolder(folder.id)
                }}
                type="button"
              >
                <span className="sr-only">Open {folder.name}</span>
              </button>
              <CardHeader>
                <CardTitle className="flex min-w-0 items-center gap-2">
                  <FolderIcon className="text-primary size-4 shrink-0" />
                  <span className="truncate">{folder.name}</span>
                </CardTitle>
                <CardAction className="relative z-10">
                  <FolderActions folder={folder} />
                </CardAction>
              </CardHeader>
              <CardContent>
                <p className="text-muted-foreground text-xs">
                  {String(folder.file_count)} {folder.file_count === 1 ? "file" : "files"} ·{" "}
                  {formatBytes(folder.total_bytes)} · Updated {relativeDateTime(folder.updated_at)}
                </p>
              </CardContent>
            </Card>
          ))}
        </div>
      ) : null}
    </section>
  )
}

export function NewFolderButton() {
  const [open, setOpen] = useState(false)

  return (
    <>
      <Button
        onClick={() => {
          setOpen(true)
        }}
        type="button"
        variant="outline"
      >
        <PlusIcon data-icon="inline-start" />
        New Folder
      </Button>
      <FolderDialog open={open} onOpenChange={setOpen} />
    </>
  )
}
