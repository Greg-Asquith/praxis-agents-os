// apps/web/src/features/knowledge/components/document-detail-header.tsx

import { useState } from "react"
import { useNavigate } from "@tanstack/react-router"
import { LockIcon, PencilIcon, RefreshCwIcon, Trash2Icon } from "lucide-react"

import { PageHeader } from "@/components/shell/page-header"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { useDeleteDocumentMutation } from "@/features/knowledge/api/delete-document"
import { useReprocessDocumentMutation } from "@/features/knowledge/api/reprocess-document"
import { useUpdateDocumentMutation } from "@/features/knowledge/api/update-document"
import { DocumentStatusBadge } from "@/features/knowledge/components/document-status-badge"
import { ManualDocumentForm } from "@/features/knowledge/components/manual-document-form"
import { SourceTypeBadge } from "@/features/knowledge/components/source-type-badge"
import type { KbDocumentDetail } from "@/features/knowledge/types"
import { getErrorMessage } from "@/lib/api/errors"
import { formatDateTime } from "@/lib/format"

export function DocumentDetailHeader({
  canMakePrivate,
  canWrite,
  document,
}: {
  canMakePrivate: boolean
  canWrite: boolean
  document: KbDocumentDetail
}) {
  const navigate = useNavigate()
  const reprocessMutation = useReprocessDocumentMutation()
  const updateMutation = useUpdateDocumentMutation()
  const deleteMutation = useDeleteDocumentMutation()
  const [editOpen, setEditOpen] = useState(false)
  const [privacyOpen, setPrivacyOpen] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function runAction(action: () => Promise<unknown>) {
    setError(null)
    try {
      await action()
      return true
    } catch (actionError) {
      setError(getErrorMessage(actionError))
      return false
    }
  }

  const canReprocess = canWrite && document.status !== "pending" && document.status !== "processing"

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        actions={
          canWrite ? (
            <div className="flex flex-wrap items-center justify-end gap-2">
              {document.source_type === "manual" ? (
                <Button
                  onClick={() => {
                    setEditOpen(true)
                  }}
                  type="button"
                  variant="outline"
                >
                  <PencilIcon data-icon="inline-start" />
                  Edit
                </Button>
              ) : null}
              {canMakePrivate && !document.is_private ? (
                <Button
                  onClick={() => {
                    setPrivacyOpen(true)
                  }}
                  type="button"
                  variant="outline"
                >
                  <LockIcon data-icon="inline-start" />
                  Make Private
                </Button>
              ) : null}
              {canReprocess ? (
                <Button
                  disabled={reprocessMutation.isPending}
                  onClick={() => void runAction(() => reprocessMutation.mutateAsync(document.id))}
                  type="button"
                  variant="outline"
                >
                  <RefreshCwIcon data-icon="inline-start" />
                  Reprocess
                </Button>
              ) : null}
              <Button
                onClick={() => {
                  setDeleteOpen(true)
                }}
                type="button"
                variant="destructive"
              >
                <Trash2Icon data-icon="inline-start" />
                Delete
              </Button>
            </div>
          ) : null
        }
        description={
          <span className="flex flex-wrap items-center gap-2">
            <SourceTypeBadge sourceType={document.source_type} />
            <DocumentStatusBadge status={document.status} />
            {document.is_private ? (
              <Badge variant="outline">
                <LockIcon data-icon="inline-start" />
                Private
              </Badge>
            ) : (
              <Badge variant="outline">Workspace</Badge>
            )}
          </span>
        }
        title={document.title}
      />
      <dl className="text-muted-foreground flex flex-wrap gap-x-6 gap-y-2 text-xs">
        <div>
          <dt className="text-foreground inline font-medium">Chunks: </dt>
          <dd className="inline">{document.chunk_count}</dd>
        </div>
        <div>
          <dt className="text-foreground inline font-medium">Created: </dt>
          <dd className="inline">{formatDateTime(document.created_at)}</dd>
        </div>
        <div>
          <dt className="text-foreground inline font-medium">Updated: </dt>
          <dd className="inline">{formatDateTime(document.updated_at)}</dd>
        </div>
        {document.processing_attempts > 0 ? (
          <div>
            <dt className="text-foreground inline font-medium">Processing attempts: </dt>
            <dd className="inline">{document.processing_attempts}</dd>
          </div>
        ) : null}
      </dl>
      {error ? (
        <Alert variant="destructive">
          <AlertTitle>Document action failed</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}
      <Dialog open={editOpen} onOpenChange={setEditOpen}>
        <DialogContent className="sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>Edit Knowledge Base Document</DialogTitle>
            <DialogDescription>Update the title or Markdown agents can retrieve.</DialogDescription>
          </DialogHeader>
          <ManualDocumentForm
            document={document}
            onSaved={() => {
              setEditOpen(false)
            }}
          />
        </DialogContent>
      </Dialog>
      <ConfirmDialog
        confirmIcon={<LockIcon data-icon="inline-start" />}
        confirmLabel="Make Private"
        confirmPendingLabel="Updating…"
        description="Only you will be able to find or read this document. This change cannot be reversed in the current version."
        isPending={updateMutation.isPending}
        onConfirm={async () => {
          const succeeded = await runAction(() =>
            updateMutation.mutateAsync({
              documentId: document.id,
              payload: { is_private: true },
            })
          )
          if (succeeded) {
            setPrivacyOpen(false)
          }
        }}
        onOpenChange={setPrivacyOpen}
        open={privacyOpen}
        title="Make this document private?"
        variant="default"
      />
      <ConfirmDialog
        confirmIcon={<Trash2Icon data-icon="inline-start" />}
        confirmLabel="Delete Document"
        confirmPendingLabel="Deleting…"
        description="The document and its searchable chunks will be removed from the workspace."
        isPending={deleteMutation.isPending}
        onConfirm={async () => {
          const succeeded = await runAction(() => deleteMutation.mutateAsync(document.id))
          if (!succeeded) {
            return
          }
          setDeleteOpen(false)
          await navigate({ to: "/knowledge" })
        }}
        onOpenChange={setDeleteOpen}
        open={deleteOpen}
        title="Delete this Knowledge Base document?"
      />
    </div>
  )
}
