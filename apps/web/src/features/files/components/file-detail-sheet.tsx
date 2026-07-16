// apps/web/src/features/files/components/file-detail-sheet.ts

import { useState } from "react"
import { DownloadIcon, ExternalLinkIcon, Trash2Icon } from "lucide-react"

import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { useDeleteFileMutation } from "@/features/files/api/delete-file"
import { useFileQuery } from "@/features/files/api/get-file"
import { useRevisionContentQuery } from "@/features/files/api/get-revision-content"
import { useFileRevisionsQuery } from "@/features/files/api/list-file-revisions"
import { FileContentView } from "@/features/files/components/file-content-view"
import { FileRevisionsList } from "@/features/files/components/file-revisions-list"
import { FileStatusBadge } from "@/features/files/components/file-status-badge"
import { openWorkspaceFile } from "@/features/files/file-actions"
import { fileCategoryLabel } from "@/features/files/format"
import type { WorkspaceFile } from "@/features/files/types"
import { getErrorMessage } from "@/lib/api/errors"
import { formatBytes, formatDateTime } from "@/lib/format"

export function FileDetailSheet({
  fileId,
  onClose,
}: {
  fileId: string | null
  onClose: () => void
}) {
  if (!fileId) {
    return null
  }

  return <FileDetailDialog fileId={fileId} onClose={onClose} />
}

function FileDetailDialog({ fileId, onClose }: { fileId: string; onClose: () => void }) {
  const { data: file } = useFileQuery(fileId)
  const { data: revisions } = useFileRevisionsQuery(fileId)
  const deleteMutation = useDeleteFileMutation()
  const [error, setError] = useState<string | null>(null)
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)

  async function handleOpen(forceDownload: boolean) {
    setError(null)
    try {
      await openWorkspaceFile({ fileId: file.id, name: file.name }, { forceDownload })
    } catch (downloadError) {
      setError(getErrorMessage(downloadError))
    }
  }

  async function handleDelete() {
    setError(null)

    try {
      await deleteMutation.mutateAsync({ fileId: file.id })
      setDeleteDialogOpen(false)
      onClose()
    } catch (deleteError) {
      setError(getErrorMessage(deleteError))
      setDeleteDialogOpen(false)
    }
  }

  return (
    <>
      <Dialog
        open
        onOpenChange={(open) => {
          if (!open) {
            onClose()
          }
        }}
      >
        <DialogContent className="top-0 right-0 left-auto h-dvh w-full max-w-full translate-x-0 translate-y-0 grid-rows-[auto_minmax(0,1fr)_auto] gap-0 overflow-hidden rounded-none p-0 sm:max-w-3xl">
          <DialogHeader className="border-b p-5 pr-12">
            <div className="flex min-w-0 flex-col gap-3">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="outline">{fileCategoryLabel(file.category)}</Badge>
                <FileStatusBadge status={file.processing_status} />
              </div>
              <div className="min-w-0">
                <DialogTitle className="truncate text-xl">{file.name}</DialogTitle>
                <DialogDescription className="mt-2">
                  {file.content_type} · {formatBytes(file.size_bytes)} ·{" "}
                  {String(file.revision_count)} revisions
                </DialogDescription>
              </div>
            </div>
          </DialogHeader>

          <div className="min-h-0 overflow-auto p-5">
            {error ? <p className="text-destructive mb-4 text-sm">{error}</p> : null}
            <FileMetadata file={file} />
            <Tabs className="mt-6" defaultValue="revisions">
              <TabsList>
                <TabsTrigger value="revisions">Revisions</TabsTrigger>
                {file.category === "editable_text" ? (
                  <TabsTrigger value="content">Content</TabsTrigger>
                ) : null}
              </TabsList>
              <TabsContent className="mt-4" value="revisions">
                <FileRevisionsList
                  file={file}
                  onRestored={() => {
                    setError(null)
                  }}
                  revisions={revisions.revisions}
                />
              </TabsContent>
              {file.category === "editable_text" ? (
                <TabsContent className="mt-4" value="content">
                  <CurrentRevisionContent file={file} />
                </TabsContent>
              ) : null}
            </Tabs>
          </div>

          <DialogFooter className="mr-1 mb-1 rounded-none">
            <Button
              disabled={deleteMutation.isPending}
              onClick={() => {
                setDeleteDialogOpen(true)
              }}
              type="button"
              variant="destructive"
            >
              <Trash2Icon data-icon="inline-start" />
              {deleteMutation.isPending ? "Deleting" : "Delete"}
            </Button>
            <Button
              onClick={() => {
                void handleOpen(true)
              }}
              type="button"
              variant="outline"
            >
              <DownloadIcon data-icon="inline-start" />
              Download
            </Button>
            <Button
              onClick={() => {
                void handleOpen(false)
              }}
              type="button"
              variant="outline"
            >
              <ExternalLinkIcon data-icon="inline-start" />
              Open
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <ConfirmDialog
        confirmIcon={<Trash2Icon data-icon="inline-start" />}
        confirmLabel="Delete File"
        confirmPendingLabel="Deleting"
        description={`This deletes ${file.name}.`}
        isPending={deleteMutation.isPending}
        onConfirm={handleDelete}
        onOpenChange={setDeleteDialogOpen}
        open={deleteDialogOpen}
        title="Delete file?"
      />
    </>
  )
}

function FileMetadata({ file }: { file: WorkspaceFile }) {
  return (
    <dl className="grid gap-3 rounded-md border p-3 text-sm sm:grid-cols-2">
      <div>
        <dt className="text-muted-foreground text-xs">Created</dt>
        <dd className="mt-1">{formatDateTime(file.created_at)}</dd>
      </div>
      <div>
        <dt className="text-muted-foreground text-xs">Updated</dt>
        <dd className="mt-1">{formatDateTime(file.updated_at)}</dd>
      </div>
      <div>
        <dt className="text-muted-foreground text-xs">Current revision</dt>
        <dd className="mt-1 font-mono text-xs">{file.current_revision_id}</dd>
      </div>
      <div>
        <dt className="text-muted-foreground text-xs">Content hash</dt>
        <dd className="mt-1 truncate font-mono text-xs">{file.content_hash}</dd>
      </div>
      {file.processing_error ? (
        <div className="sm:col-span-2">
          <dt className="text-muted-foreground text-xs">Processing error</dt>
          <dd className="text-destructive mt-1">{file.processing_error}</dd>
        </div>
      ) : null}
    </dl>
  )
}

function CurrentRevisionContent({ file }: { file: WorkspaceFile }) {
  const { data } = useRevisionContentQuery(file.id, file.current_revision_id)

  return (
    <FileContentView
      className="max-h-[60vh]"
      content={data.content}
      mediaType={file.content_type}
      name={file.name}
    />
  )
}
