// apps/web/src/features/files/components/file-revisions-list.ts

import { useMemo, useState } from "react"
import { useSuspenseQueries } from "@tanstack/react-query"
import { CheckIcon, RotateCcwIcon } from "lucide-react"

import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { agentsQueryOptions } from "@/features/agents/api/list-agents"
import { useRevisionContentQuery } from "@/features/files/api/get-revision-content"
import { useRestoreFileRevisionMutation } from "@/features/files/api/restore-file-revision"
import { RevisionDiff } from "@/features/files/components/revision-diff"
import { fileRevisionKindLabel } from "@/features/files/format"
import type { FileRevision, WorkspaceFile } from "@/features/files/types"
import { workspaceMembershipsQueryOptions } from "@/features/workspaces/api/list-memberships"
import { useActiveWorkspace } from "@/features/workspaces/components/use-active-workspace"
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
  const actorLabels = useActorLabels()
  const canCompare = file.category === "editable_text" && revisions.length > 1
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
            actor={actorLabels(revision)}
            baseRevisionId={baseRevisionId}
            canCompare={canCompare}
            setBaseRevisionId={setBaseRevisionId}
            setCompareRevisionId={setCompareRevisionId}
          />
        ))}
      </div>
      <ConfirmDialog
        confirmIcon={<RotateCcwIcon data-icon="inline-start" />}
        confirmLabel="Restore Version"
        confirmPendingLabel="Restoring"
        description={
          revisionToRestore
            ? `Restore ${file.name} to version ${String(
                revisionToRestore.revision_number
              )}. A new current version will be created.`
            : "A new current version will be created."
        }
        isPending={restoreMutation.isPending}
        onConfirm={confirmRestoreRevision}
        onOpenChange={(open) => {
          if (!open) {
            setRevisionToRestore(null)
          }
        }}
        open={revisionToRestore !== null}
        title="Restore this version?"
        variant="default"
      />
      {canCompare && baseRevision && compareRevision ? (
        <RevisionDiffPanel
          baseRevision={baseRevision}
          compareRevision={compareRevision}
          fileId={file.id}
        />
      ) : null}
    </div>
  )
}

function RevisionRow({
  actor,
  baseRevisionId,
  canCompare,
  compareRevisionId,
  file,
  isRestoring,
  onRestore,
  revision,
  setBaseRevisionId,
  setCompareRevisionId,
}: {
  actor: string
  baseRevisionId: string | null
  canCompare: boolean
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
              Version {revision.revision_number}
            </Badge>
            <Badge variant="secondary">{fileRevisionKindLabel(revision.revision_kind)}</Badge>
            {isCurrentRevision ? <Badge variant="outline">Current</Badge> : null}
          </div>
          <p className="text-muted-foreground mt-2 text-xs">
            {actor} · {formatBytes(revision.size_bytes)} · {formatDateTime(revision.created_at)}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {canCompare ? (
            <>
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
            </>
          ) : null}
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
      leftLabel={`version ${String(baseRevision.revision_number)}`}
      rightContent={compareContent.content}
      rightLabel={`version ${String(compareRevision.revision_number)}`}
    />
  )
}

function useActorLabels() {
  const { workspace } = useActiveWorkspace()
  const [{ data: memberships }, { data: agents }] = useSuspenseQueries({
    queries: [
      workspaceMembershipsQueryOptions(workspace.id),
      agentsQueryOptions({ includeInactive: true, limit: 100 }),
    ],
  })
  const userLabels = useMemo(
    () =>
      new Map(
        memberships.memberships.map((membership) => [
          membership.user_id,
          firstNonEmpty([membership.user_display_name, membership.user_email], "A teammate"),
        ])
      ),
    [memberships.memberships]
  )
  const agentLabels = useMemo(
    () =>
      new Map(agents.agents.map((agent) => [agent.id, firstNonEmpty([agent.name], "An agent")])),
    [agents.agents]
  )

  return (revision: FileRevision) => {
    if (revision.created_by_system) {
      return "System"
    }
    if (revision.created_by_agent_id) {
      return agentLabels.get(revision.created_by_agent_id) ?? "An agent"
    }
    if (revision.created_by_user_id) {
      return userLabels.get(revision.created_by_user_id) ?? "A teammate"
    }
    return "A teammate"
  }
}

function firstNonEmpty(values: (string | null)[], fallback: string) {
  return values.find((value) => value?.trim())?.trim() ?? fallback
}
