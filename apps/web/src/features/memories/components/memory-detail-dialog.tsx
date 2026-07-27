// apps/web/src/features/memories/components/memory-detail-dialog.tsx

import { useState } from "react"
import { PencilIcon, Trash2Icon } from "lucide-react"

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
import { Separator } from "@/components/ui/separator"
import { useDeleteMemoryMutation } from "@/features/memories/api/delete-memory"
import { useMemoryDetailQuery } from "@/features/memories/api/get-memory"
import {
  formatMemoryConfidence,
  memoryScopeLabel,
} from "@/features/memories/components/memory-display"
import { MemoryEditForm } from "@/features/memories/components/memory-edit-form"
import { SupersessionChain } from "@/features/memories/components/supersession-chain"
import type { Memory } from "@/features/memories/types"
import { getErrorMessage } from "@/lib/api/errors"
import { formatDateTime, titleCaseToken } from "@/lib/format"

export function MemoryDetailDialog({
  canEdit,
  isManager,
  memoryId,
  onMemoryIdChange,
  onOpenChange,
  open,
}: {
  canEdit: boolean
  isManager: boolean
  memoryId: string
  onMemoryIdChange: (memoryId: string) => void
  onOpenChange: (open: boolean) => void
  open: boolean
}) {
  const { data } = useMemoryDetailQuery(memoryId)
  const [editing, setEditing] = useState(false)
  const [deleteMode, setDeleteMode] = useState<"archive" | "purge" | null>(null)
  const [error, setError] = useState<string | null>(null)
  const deleteMutation = useDeleteMemoryMutation()
  const memory = data.memory
  const canDelete = canEdit && (memory.scope !== "workspace" || isManager)
  const canEditActive = canEdit && memory.status === "active"
  const canArchive = canDelete && memory.status === "active"
  const hasActions = canEditActive || canDelete

  function selectMemory(nextMemoryId: string) {
    setEditing(false)
    setError(null)
    onMemoryIdChange(nextMemoryId)
  }

  async function remove() {
    if (deleteMode === null) {
      return
    }
    setError(null)
    try {
      await deleteMutation.mutateAsync({
        memoryId: memory.id,
        purge: deleteMode === "purge",
      })
      setDeleteMode(null)
      onOpenChange(false)
    } catch (mutationError) {
      setError(getErrorMessage(mutationError))
    }
  }

  return (
    <>
      <Dialog
        open={open}
        onOpenChange={(nextOpen) => {
          if (!nextOpen) {
            setEditing(false)
          }
          onOpenChange(nextOpen)
        }}
      >
        <DialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-3xl">
          <DialogHeader>
            <div className="flex flex-wrap items-center gap-2 pr-8">
              <DialogTitle>{memory.title}</DialogTitle>
              <Badge variant={memory.kind === "core" ? "warning" : "secondary"}>
                {titleCaseToken(memory.kind, "Memory")}
              </Badge>
              <Badge variant="outline">{memoryScopeLabel(memory)}</Badge>
            </div>
            <DialogDescription>
              Review what agents remember and correct anything that is no longer accurate.
            </DialogDescription>
          </DialogHeader>
          {error ? (
            <Alert variant="destructive">
              <AlertTitle>Memory action failed</AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          ) : null}
          {editing ? (
            <MemoryEditForm
              key={memory.id}
              memory={memory}
              onSaved={(updated) => {
                selectMemory(updated.id)
              }}
            />
          ) : (
            <MemoryDetail memory={memory} />
          )}
          <SupersessionChain chain={data.chain} currentId={memory.id} onSelect={selectMemory} />
          {hasActions ? (
            <>
              <Separator />
              <div className="flex flex-wrap justify-between gap-3">
                {canEditActive ? (
                  <Button
                    onClick={() => {
                      setEditing((current) => !current)
                    }}
                    type="button"
                    variant="outline"
                  >
                    <PencilIcon data-icon="inline-start" />
                    {editing ? "Cancel Editing" : "Edit Memory"}
                  </Button>
                ) : null}
                {canDelete ? (
                  <div className="ml-auto flex flex-wrap gap-2">
                    {canArchive ? (
                      <Button
                        onClick={() => {
                          setDeleteMode("archive")
                        }}
                        type="button"
                        variant="outline"
                      >
                        Archive
                      </Button>
                    ) : null}
                    <Button
                      onClick={() => {
                        setDeleteMode("purge")
                      }}
                      type="button"
                      variant="destructive"
                    >
                      <Trash2Icon data-icon="inline-start" />
                      Delete Permanently
                    </Button>
                  </div>
                ) : null}
              </div>
            </>
          ) : null}
        </DialogContent>
      </Dialog>
      <ConfirmDialog
        confirmIcon={<Trash2Icon data-icon="inline-start" />}
        confirmLabel={deleteMode === "purge" ? "Delete Permanently" : "Archive Memory"}
        confirmPendingLabel={deleteMode === "purge" ? "Deleting…" : "Archiving…"}
        description={
          deleteMode === "purge"
            ? "This permanently removes the memory. Its audit history remains, but the content cannot be restored."
            : "The memory will stop appearing in active results and agent context. Its history remains available."
        }
        isPending={deleteMutation.isPending}
        onConfirm={remove}
        onOpenChange={(nextOpen) => {
          if (!nextOpen) {
            setDeleteMode(null)
          }
        }}
        open={deleteMode !== null}
        title={deleteMode === "purge" ? "Delete this memory permanently?" : "Archive this memory?"}
      />
    </>
  )
}

function MemoryDetail({ memory }: { memory: Memory }) {
  return (
    <div className="flex flex-col gap-5">
      <div className="bg-muted/40 rounded-lg p-4 text-sm leading-6 whitespace-pre-wrap">
        {memory.content_md}
      </div>
      <dl className="grid gap-4 text-sm sm:grid-cols-2 lg:grid-cols-3">
        <Detail label="Type" value={titleCaseToken(memory.memory_type, "Memory")} />
        <Detail
          label="Created by"
          value={`${titleCaseToken(memory.created_by, "Unknown")} · ${titleCaseToken(memory.source, "Unknown")}`}
        />
        <Detail label="Importance" value={`${String(memory.importance)} of 5`} />
        <Detail label="Stored confidence" value={formatMemoryConfidence(memory.confidence)} />
        <Detail
          label="Effective confidence"
          value={formatMemoryConfidence(memory.effective_confidence)}
        />
        <Detail label="Updated" value={formatDateTime(memory.updated_at)} />
        {memory.expires_at ? (
          <Detail label="Expires" value={formatDateTime(memory.expires_at)} />
        ) : null}
        {memory.archived_at ? (
          <Detail label="Archived" value={formatDateTime(memory.archived_at)} />
        ) : null}
      </dl>
    </div>
  )
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-muted-foreground text-xs">{label}</dt>
      <dd className="mt-1">{value}</dd>
    </div>
  )
}
