// apps/web/src/features/memories/components/memory-detail-dialog.tsx

import { useId, useState } from "react"
import { Link } from "@tanstack/react-router"
import { ChevronDownIcon, EraserIcon, PencilIcon, Trash2Icon } from "lucide-react"

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
import { Field, FieldContent, FieldDescription, FieldLabel } from "@/components/ui/field"
import { Separator } from "@/components/ui/separator"
import { Switch } from "@/components/ui/switch"
import { useDeleteMemoryMutation } from "@/features/memories/api/delete-memory"
import { useMemoryDetailQuery } from "@/features/memories/api/get-memory"
import { useUpdateMemoryMutation } from "@/features/memories/api/update-memory"
import {
  MEMORY_STATUS_LABELS,
  formatMemoryConfidence,
  MEMORY_AUDIENCE_LABELS,
  memoryOrigin,
  memoryUsedByLabel,
} from "@/features/memories/components/memory-display"
import { MemoryEditForm } from "@/features/memories/components/memory-edit-form"
import { MemoryOriginBadge } from "@/features/memories/components/memory-origin-badge"
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
  const [deleteMode, setDeleteMode] = useState<"forget" | "purge" | null>(null)
  const [error, setError] = useState<string | null>(null)
  const deleteMutation = useDeleteMemoryMutation()
  const memory = data.memory
  const canDelete = canEdit && (memory.scope !== "workspace" || isManager)
  const canEditActive = canEdit && memory.status === "active"
  const canForget = canDelete && memory.status === "active"

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
        <DialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle className="pr-8">{memory.title}</DialogTitle>
            <DialogDescription className="flex flex-wrap items-center gap-2">
              <MemoryOriginBadge memory={memory} />
              <Badge variant="outline">
                {MEMORY_AUDIENCE_LABELS[memory.scope === "user" ? "private" : "shared"]}
              </Badge>
              <Badge variant="outline">Used By {memoryUsedByLabel(memory)}</Badge>
              {memory.status === "active" ? null : (
                <Badge variant="warning">{MEMORY_STATUS_LABELS[memory.status]}</Badge>
              )}
            </DialogDescription>
          </DialogHeader>
          {error ? (
            <Alert variant="destructive">
              <AlertTitle>Memory Action Failed</AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          ) : null}
          {editing ? (
            <MemoryEditForm
              key={memory.id}
              memory={memory}
              onCancel={() => {
                setEditing(false)
              }}
              onSaved={(updated) => {
                selectMemory(updated.id)
              }}
            />
          ) : (
            <>
              <div className="bg-muted/40 rounded-lg p-4 text-sm leading-6 whitespace-pre-wrap">
                {memory.content_md}
              </div>
              <WhereThisCameFrom memory={memory} />
              <RecallSwitch disabled={!canEditActive} memory={memory} />
            </>
          )}
          <SupersessionChain chain={data.chain} currentId={memory.id} onSelect={selectMemory} />
          <AdvancedDetails
            canPurge={canDelete}
            memory={memory}
            onPurge={() => {
              setDeleteMode("purge")
            }}
          />
          {!editing && (canEditActive || canForget) ? (
            <>
              <Separator />
              <div className="flex flex-wrap justify-end gap-2">
                {canForget ? (
                  <Button
                    onClick={() => {
                      setDeleteMode("forget")
                    }}
                    type="button"
                    variant="outline"
                  >
                    <EraserIcon data-icon="inline-start" />
                    Forget
                  </Button>
                ) : null}
                {canEditActive ? (
                  <Button
                    onClick={() => {
                      setEditing(true)
                    }}
                    type="button"
                  >
                    <PencilIcon data-icon="inline-start" />
                    Edit
                  </Button>
                ) : null}
              </div>
            </>
          ) : null}
        </DialogContent>
      </Dialog>
      <ConfirmDialog
        confirmIcon={
          deleteMode === "purge" ? (
            <Trash2Icon data-icon="inline-start" />
          ) : (
            <EraserIcon data-icon="inline-start" />
          )
        }
        confirmLabel={deleteMode === "purge" ? "Delete Permanently" : "Forget"}
        confirmPendingLabel={deleteMode === "purge" ? "Deleting…" : "Forgetting…"}
        description={
          deleteMode === "purge"
            ? "This permanently removes the memory. Its audit history remains, but the content can't be restored."
            : "Agents stop using this memory, and Praxis won't learn it again by itself. You can still find it under Archived."
        }
        isPending={deleteMutation.isPending}
        onConfirm={remove}
        onOpenChange={(nextOpen) => {
          if (!nextOpen) {
            setDeleteMode(null)
          }
        }}
        open={deleteMode !== null}
        title={deleteMode === "purge" ? "Delete this memory permanently?" : "Forget this memory?"}
      />
    </>
  )
}

function WhereThisCameFrom({ memory }: { memory: Memory }) {
  const origin = memoryOrigin(memory)
  const conversation = memory.source_conversation_id ? (
    <Link
      className="text-link underline-offset-4 hover:underline"
      params={{ conversationId: memory.source_conversation_id }}
      to="/conversations/$conversationId"
    >
      {memory.source_conversation_title ?? "Untitled conversation"}
    </Link>
  ) : null
  const agent = memory.agent_name ?? "An agent"

  return (
    <section className="flex flex-col gap-1 text-sm">
      <h3 className="font-heading font-medium">Where This Came From</h3>
      <p className="text-muted-foreground">
        {origin === "learned" ? "Learned automatically" : null}
        {origin === "agent" ? `${agent} saved this` : null}
        {origin === "person" ? "A person wrote or corrected this" : null}
        {conversation ? <> from {conversation}</> : null}
        {`, ${formatDateTime(memory.created_at)}.`}
        {origin === "person" && memory.last_edited_by_user_at
          ? ` Last edited ${formatDateTime(memory.last_edited_by_user_at)}.`
          : null}
      </p>
    </section>
  )
}

function RecallSwitch({ disabled, memory }: { disabled: boolean; memory: Memory }) {
  const switchId = useId()
  const mutation = useUpdateMemoryMutation()

  return (
    <Field data-disabled={disabled || mutation.isPending} orientation="horizontal">
      <FieldContent>
        <FieldLabel htmlFor={switchId}>Bring Up Automatically</FieldLabel>
        <FieldDescription id={`${switchId}-description`}>
          {mutation.error
            ? getErrorMessage(mutation.error)
            : "Comes up by itself in conversations it relates to. When off, agents only find it by searching."}
        </FieldDescription>
      </FieldContent>
      <Switch
        aria-describedby={`${switchId}-description`}
        checked={memory.recall_disabled_at === null}
        disabled={disabled || mutation.isPending}
        id={switchId}
        onCheckedChange={(checked) => {
          mutation.mutate({ memoryId: memory.id, payload: { recall_disabled: !checked } })
        }}
      />
    </Field>
  )
}

function AdvancedDetails({
  canPurge,
  memory,
  onPurge,
}: {
  canPurge: boolean
  memory: Memory
  onPurge: () => void
}) {
  const [open, setOpen] = useState(false)
  const panelId = useId()

  return (
    <section className="flex flex-col gap-3">
      <Button
        aria-controls={panelId}
        aria-expanded={open}
        className="text-muted-foreground w-fit"
        onClick={() => {
          setOpen((current) => !current)
        }}
        size="sm"
        type="button"
        variant="ghost"
      >
        Advanced
        <ChevronDownIcon
          className={open ? "rotate-180 transition-transform" : "transition-transform"}
          data-icon="inline-end"
        />
      </Button>
      {open ? (
        <div className="flex flex-col gap-4" id={panelId}>
          <dl className="grid gap-4 text-sm sm:grid-cols-3">
            <Detail label="Type" value={titleCaseToken(memory.memory_type, "Memory")} />
            <Detail label="Importance" value={`${String(memory.importance)} of 5`} />
            <Detail
              label="Confidence"
              value={formatMemoryConfidence(memory.effective_confidence)}
            />
            <Detail
              label="Expires"
              value={memory.expires_at ? formatDateTime(memory.expires_at) : "Never"}
            />
            <Detail label="Last Changed" value={formatDateTime(memory.updated_at)} />
            {memory.archived_at ? (
              <Detail label="Archived" value={formatDateTime(memory.archived_at)} />
            ) : null}
          </dl>
          {canPurge ? (
            <Button
              className="w-fit"
              onClick={onPurge}
              size="sm"
              type="button"
              variant="destructive"
            >
              <Trash2Icon data-icon="inline-start" />
              Delete Permanently
            </Button>
          ) : null}
        </div>
      ) : null}
    </section>
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
