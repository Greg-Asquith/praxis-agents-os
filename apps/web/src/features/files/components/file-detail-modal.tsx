// apps/web/features/files/components/file-detail-modal.tsx

import { Suspense, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { DownloadIcon, ExternalLinkIcon, PencilIcon, Trash2Icon } from "lucide-react"

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
import { Skeleton } from "@/components/ui/skeleton"
import { useDeleteFileMutation } from "@/features/files/api/delete-file"
import { fileQueryOptions } from "@/features/files/api/get-file"
import { useRevisionContentQuery } from "@/features/files/api/get-revision-content"
import { useFileRevisionsQuery } from "@/features/files/api/list-file-revisions"
import { filePreviewQueryOptions } from "@/features/files/api/preview-file"
import { FileContentView } from "@/features/files/components/file-content-view"
import { FileRevisionsList } from "@/features/files/components/file-revisions-list"
import { FileStatusBadge } from "@/features/files/components/file-status-badge"
import { RenameFileDialog } from "@/features/files/components/rename-file-dialog"
import { openWorkspaceFile } from "@/features/files/file-actions"
import { fileCategoryLabel } from "@/features/files/format"
import type { WorkspaceFile } from "@/features/files/types"
import { ApiError, getErrorMessage } from "@/lib/api/errors"
import { formatBytes, formatDateTime } from "@/lib/format"

export function FileDetailModal({
  fileId,
  initialFile = null,
  open,
  onOpenChange,
}: {
  fileId: string | null
  initialFile?: WorkspaceFile | null
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  if (!open || !fileId) {
    return null
  }

  return <FileDetailQuery fileId={fileId} initialFile={initialFile} onOpenChange={onOpenChange} />
}

function FileDetailQuery({
  fileId,
  initialFile,
  onOpenChange,
}: {
  fileId: string
  initialFile: WorkspaceFile | null
  onOpenChange: (open: boolean) => void
}) {
  const fileQuery = useQuery({
    ...fileQueryOptions(fileId),
    ...(initialFile ? { initialData: initialFile } : {}),
    refetchOnMount: "always",
    staleTime: 0,
  })

  if (fileQuery.isPending) {
    return <FileDetailLoadingDialog onOpenChange={onOpenChange} />
  }
  if (fileQuery.error && !fileQuery.isFetching) {
    return (
      <FileDetailErrorDialog
        error={fileQuery.error}
        onOpenChange={onOpenChange}
        onRetry={() => {
          void fileQuery.refetch()
        }}
      />
    )
  }
  if (!fileQuery.data) {
    return <FileDetailLoadingDialog onOpenChange={onOpenChange} />
  }

  return <FileDetailDialog file={fileQuery.data} onOpenChange={onOpenChange} />
}

function FileDetailDialog({
  file,
  onOpenChange,
}: {
  file: WorkspaceFile
  onOpenChange: (open: boolean) => void
}) {
  const deleteMutation = useDeleteFileMutation()
  const [error, setError] = useState<string | null>(null)
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  const [renameDialogOpen, setRenameDialogOpen] = useState(false)

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
      onOpenChange(false)
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
          onOpenChange(open)
        }}
      >
        <DialogContent className="max-h-[calc(100dvh-2rem)] grid-rows-[auto_minmax(0,1fr)_auto] gap-0 overflow-hidden p-0 sm:max-w-3xl">
          <DialogHeader className="border-b p-5 pr-12">
            <div className="flex min-w-0 flex-col gap-3">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="outline">{fileCategoryLabel(file.category)}</Badge>
                {file.processing_status !== "ready" ? (
                  <FileStatusBadge status={file.processing_status} />
                ) : null}
              </div>
              <div className="min-w-0">
                <div className="flex min-w-0 items-center gap-2">
                  <DialogTitle className="truncate text-xl">{file.name}</DialogTitle>
                  <Button
                    aria-label={`Rename ${file.name}`}
                    onClick={() => {
                      setRenameDialogOpen(true)
                    }}
                    size="icon-sm"
                    type="button"
                    variant="ghost"
                  >
                    <PencilIcon />
                  </Button>
                </div>
                <DialogDescription className="mt-2">
                  {fileCategoryLabel(file.category)} · {formatBytes(file.size_bytes)} · Updated{" "}
                  {formatDateTime(file.updated_at)}
                </DialogDescription>
                {file.description ? (
                  <p className="text-muted-foreground mt-2 text-sm">{file.description}</p>
                ) : null}
              </div>
            </div>
          </DialogHeader>

          <div className="min-h-0 space-y-6 overflow-auto p-5">
            {error ? <p className="text-destructive text-sm">{error}</p> : null}
            <Suspense fallback={<PreviewSkeleton />}>
              <FilePreview file={file} />
            </Suspense>
            <FileMetadata file={file} />
            <Suspense fallback={<FileHistorySkeleton file={file} />}>
              <FileHistory
                file={file}
                onRestored={() => {
                  setError(null)
                }}
              />
            </Suspense>
            <TechnicalDetails file={file} />
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
      <RenameFileDialog file={renameDialogOpen ? file : null} onOpenChange={setRenameDialogOpen} />
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

function FileDetailLoadingDialog({ onOpenChange }: { onOpenChange: (open: boolean) => void }) {
  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[calc(100dvh-2rem)] gap-0 overflow-hidden p-0 sm:max-w-3xl">
        <DialogHeader className="border-b p-5 pr-12">
          <Skeleton className="h-6 w-24" />
          <Skeleton className="mt-3 h-7 w-80 max-w-full" />
          <Skeleton className="mt-2 h-4 w-64 max-w-full" />
        </DialogHeader>
        <div className="space-y-5 p-5">
          <PreviewSkeleton />
          <Skeleton className="h-20 w-full rounded-lg" />
        </div>
      </DialogContent>
    </Dialog>
  )
}

function FileDetailErrorDialog({
  error,
  onOpenChange,
  onRetry,
}: {
  error: Error
  onOpenChange: (open: boolean) => void
  onRetry: () => void
}) {
  const missing = error instanceof ApiError && error.status === 404

  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {missing ? "File No Longer Available" : "File Couldn’t Be Loaded"}
          </DialogTitle>
          <DialogDescription>
            {missing
              ? "This file may have been deleted since the agent used it."
              : getErrorMessage(error)}
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button
            onClick={() => {
              onOpenChange(false)
            }}
            type="button"
            variant="outline"
          >
            Close
          </Button>
          {missing ? null : (
            <Button onClick={onRetry} type="button">
              Try Again
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function PreviewSkeleton() {
  return <Skeleton className="h-64 w-full rounded-lg" aria-label="Loading preview" />
}

function FileHistory({ file, onRestored }: { file: WorkspaceFile; onRestored: () => void }) {
  const { data: revisions } = useFileRevisionsQuery(file.id)

  return (
    <section className="space-y-3" aria-labelledby="file-history-heading">
      <FileHistoryHeading file={file} />
      <FileRevisionsList file={file} onRestored={onRestored} revisions={revisions.revisions} />
    </section>
  )
}

function FileHistorySkeleton({ file }: { file: WorkspaceFile }) {
  return (
    <section className="space-y-3" aria-labelledby="file-history-heading">
      <FileHistoryHeading file={file} />
      <Skeleton className="h-24 w-full rounded-lg" />
    </section>
  )
}

function FileHistoryHeading({ file }: { file: WorkspaceFile }) {
  return (
    <div>
      <h3 className="font-heading font-medium" id="file-history-heading">
        History
      </h3>
      <p className="text-muted-foreground mt-1 text-sm">
        {file.revision_count === 1 ? "1 version" : `${String(file.revision_count)} versions`}
      </p>
    </div>
  )
}

function FilePreview({ file }: { file: WorkspaceFile }) {
  if (file.processing_status === "pending" || file.processing_status === "processing") {
    return <p className="text-muted-foreground text-sm">Praxis is still preparing this file.</p>
  }

  if (file.processing_status === "error") {
    return null
  }

  if (isSignedPreview(file)) {
    return <SignedMediaPreview file={file} />
  }

  if (file.category === "editable_text") {
    return <CurrentRevisionContent file={file} />
  }

  return (
    <p className="text-muted-foreground text-sm">
      Preview isn&apos;t available for this file type — use Open or Download.
    </p>
  )
}

function SignedMediaPreview({ file }: { file: WorkspaceFile }) {
  const previewQuery = useQuery(filePreviewQueryOptions(file.id))

  if (previewQuery.isPending) {
    return (
      <div className="bg-muted/40 h-64 animate-pulse rounded-lg" aria-label="Loading preview" />
    )
  }

  if (previewQuery.isError) {
    return <p className="text-muted-foreground text-sm">Preview is temporarily unavailable.</p>
  }

  const previewUrl = previewQuery.data.preview.url
  if (file.category === "image") {
    return (
      <div className="bg-muted/40 flex max-h-112 min-h-48 items-center justify-center overflow-hidden rounded-lg border p-3">
        <img alt={file.name} className="max-h-104 max-w-full object-contain" src={previewUrl} />
      </div>
    )
  }

  if (file.category === "video") {
    return (
      <video className="bg-muted/40 max-h-122 w-full rounded-lg border" controls src={previewUrl}>
        <track kind="captions" />
      </video>
    )
  }

  return (
    <iframe
      className="h-96 w-full rounded-lg border"
      sandbox=""
      src={previewUrl}
      title={file.name}
    />
  )
}

function FileMetadata({ file }: { file: WorkspaceFile }) {
  return (
    <dl className="grid gap-3 rounded-lg border p-3 text-sm sm:grid-cols-2">
      <div>
        <dt className="text-muted-foreground text-xs">Created</dt>
        <dd className="mt-1">{formatDateTime(file.created_at)}</dd>
      </div>
      <div>
        <dt className="text-muted-foreground text-xs">Updated</dt>
        <dd className="mt-1">{formatDateTime(file.updated_at)}</dd>
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
      className="max-h-112"
      content={data.content}
      mediaType={file.content_type}
      name={file.name}
    />
  )
}

function TechnicalDetails({ file }: { file: WorkspaceFile }) {
  return (
    <details className="group rounded-lg border px-3 py-2 text-sm">
      <summary className="cursor-pointer font-medium select-none">Technical details</summary>
      <dl className="mt-3 grid gap-3 border-t pt-3">
        <div>
          <dt className="text-muted-foreground text-xs">Current version ID</dt>
          <dd className="mt-1 font-mono text-xs break-all">{file.current_revision_id}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground text-xs">Content hash</dt>
          <dd className="mt-1 font-mono text-xs break-all">{file.content_hash}</dd>
        </div>
      </dl>
    </details>
  )
}

function isSignedPreview(file: WorkspaceFile) {
  return (
    file.category === "image" ||
    file.category === "video" ||
    file.content_type === "application/pdf"
  )
}
