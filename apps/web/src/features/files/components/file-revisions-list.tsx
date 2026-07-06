// apps/web/src/features/files/components/file-revisions-list.ts

import { useState } from "react"
import { CheckIcon, RotateCcwIcon } from "lucide-react"

import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { useRevisionContentQuery } from "@/features/files/api/get-revision-content"
import { useRestoreFileRevisionMutation } from "@/features/files/api/restore-file-revision"
import { RevisionDiff } from "@/features/files/components/revision-diff"
import { fileRevisionKindLabel, shortHash } from "@/features/files/format"
import type { FileRevision, WorkspaceFile } from "@/features/files/types"
import { getErrorMessage } from "@/lib/api/errors"
import { formatBytes, formatDateTime } from "@/lib/format"

export function FileRevisionsList({
  file,
  onRestored,
  revisions,
}: {
  file: WorkspaceFile
  onRestored: () => void
  revisions: FileRevision[]
}) {
  const restoreMutation = useRestoreFileRevisionMutation()
  const [baseRevisionId, setBaseRevisionId] = useState<string | null>(
    revisions[1]?.id ?? revisions[0]?.id ?? null
  )
  const [compareRevisionId, setCompareRevisionId] = useState<string | null>(
    revisions[0]?.id ?? null
  )
  const [error, setError] = useState<string | null>(null)
  const [revisionToRestore, setRevisionToRestore] = useState<FileRevision | null>(null)
  const baseRevision = revisions.find((revision) => revision.id === baseRevisionId) ?? null
  const compareRevision = revisions.find((revision) => revision.id === compareRevisionId) ?? null

  function handleRestore(revision: FileRevision) {
    setError(null)
    setRevisionToRestore(revision)
  }

  async function confirmRestoreRevision() {
    if (!revisionToRestore) {
      return
    }

    try {
      await restoreMutation.mutateAsync({
        expectedCurrentRevisionId: file.current_revision_id,
        fileId: file.id,
        revisionId: revisionToRestore.id,
      })
      setRevisionToRestore(null)
      onRestored()
    } catch (restoreError) {
      setError(getErrorMessage(restoreError))
      setRevisionToRestore(null)
    }
  }

  return (
    <div className="flex min-w-0 flex-col gap-4">
      {error ? <p className="text-destructive text-sm">{error}</p> : null}
      <div className="flex min-w-0 flex-col gap-2">
        {revisions.map((revision) => (
          <RevisionRow
            compareRevisionId={compareRevisionId}
            file={file}
            isRestoring={restoreMutation.isPending}
            key={revision.id}
            onRestore={handleRestore}
            revision={revision}
            baseRevisionId={baseRevisionId}
            setBaseRevisionId={setBaseRevisionId}
            setCompareRevisionId={setCompareRevisionId}
          />
        ))}
      </div>
      <ConfirmDialog
        confirmIcon={<RotateCcwIcon data-icon="inline-start" />}
        confirmLabel="Restore revision"
        confirmPendingLabel="Restoring"
        description={
          revisionToRestore
            ? `Restore ${file.name} to revision ${String(
                revisionToRestore.revision_number
              )}. A new current revision will be added.`
            : "A new current revision will be added."
        }
        isPending={restoreMutation.isPending}
        onConfirm={confirmRestoreRevision}
        onOpenChange={(open) => {
          if (!open) {
            setRevisionToRestore(null)
          }
        }}
        open={revisionToRestore !== null}
        title="Restore revision?"
        variant="default"
      />
      {file.category === "editable_text" && baseRevision && compareRevision ? (
        <RevisionDiffPanel
          baseRevision={baseRevision}
          compareRevision={compareRevision}
          fileId={file.id}
        />
      ) : (
        <div className="bg-muted/40 rounded-md border p-3 text-sm">
          Text diff is available for editable text files.
        </div>
      )}
    </div>
  )
}

function RevisionRow({
  baseRevisionId,
  compareRevisionId,
  file,
  isRestoring,
  onRestore,
  revision,
  setBaseRevisionId,
  setCompareRevisionId,
}: {
  baseRevisionId: string | null
  compareRevisionId: string | null
  file: WorkspaceFile
  isRestoring: boolean
  onRestore: (revision: FileRevision) => void
  revision: FileRevision
  setBaseRevisionId: (revisionId: string) => void
  setCompareRevisionId: (revisionId: string) => void
}) {
  const isCurrentRevision = revision.id === file.current_revision_id

  return (
    <div className="rounded-md border p-3">
      <div className="flex flex-col justify-between gap-3 md:flex-row md:items-start">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={isCurrentRevision ? "default" : "outline"}>
              Revision {revision.revision_number}
            </Badge>
            <Badge variant="secondary">{fileRevisionKindLabel(revision.revision_kind)}</Badge>
            {isCurrentRevision ? <Badge variant="outline">Current</Badge> : null}
          </div>
          <p className="text-muted-foreground mt-2 text-xs">
            {actorLabel(revision)} · {formatBytes(revision.size_bytes)} ·{" "}
            {shortHash(revision.content_hash)} · {formatDateTime(revision.created_at)}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            onClick={() => {
              setBaseRevisionId(revision.id)
            }}
            size="sm"
            type="button"
            variant={baseRevisionId === revision.id ? "default" : "outline"}
          >
            {baseRevisionId === revision.id ? <CheckIcon data-icon="inline-start" /> : null}
            Base
          </Button>
          <Button
            onClick={() => {
              setCompareRevisionId(revision.id)
            }}
            size="sm"
            type="button"
            variant={compareRevisionId === revision.id ? "default" : "outline"}
          >
            {compareRevisionId === revision.id ? <CheckIcon data-icon="inline-start" /> : null}
            Compare
          </Button>
          {!isCurrentRevision ? (
            <Button
              disabled={isRestoring}
              onClick={() => {
                onRestore(revision)
              }}
              size="sm"
              type="button"
              variant="outline"
            >
              <RotateCcwIcon data-icon="inline-start" />
              Restore
            </Button>
          ) : null}
        </div>
      </div>
    </div>
  )
}

function RevisionDiffPanel({
  baseRevision,
  compareRevision,
  fileId,
}: {
  baseRevision: FileRevision
  compareRevision: FileRevision
  fileId: string
}) {
  const { data: baseContent } = useRevisionContentQuery(fileId, baseRevision.id)
  const { data: compareContent } = useRevisionContentQuery(fileId, compareRevision.id)

  return (
    <RevisionDiff
      leftContent={baseContent.content}
      leftLabel={`revision ${String(baseRevision.revision_number)}`}
      rightContent={compareContent.content}
      rightLabel={`revision ${String(compareRevision.revision_number)}`}
    />
  )
}

function actorLabel(revision: FileRevision) {
  if (revision.created_by_system) {
    return "System"
  }
  if (revision.created_by_agent_id) {
    return `Agent ${revision.created_by_agent_id.slice(0, 8)}`
  }
  if (revision.created_by_user_id) {
    return `User ${revision.created_by_user_id.slice(0, 8)}`
  }
  return "Unknown actor"
}
