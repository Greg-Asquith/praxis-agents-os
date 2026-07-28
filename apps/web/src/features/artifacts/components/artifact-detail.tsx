// apps/web/src/features/artifacts/components/artifact-detail.tsx

import { Suspense, useState } from "react"
import { useSuspenseQueries } from "@tanstack/react-query"
import { ArrowLeftIcon, RotateCcwIcon } from "lucide-react"
import { Link } from "@tanstack/react-router"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { RevisionDiff } from "@/components/ui/revision-diff"
import { PageHeader } from "@/components/shell/page-header"
import { artifactVersionContentQueryOptions } from "@/features/artifacts/api/get-artifact-version-content"
import { useArtifactQuery } from "@/features/artifacts/api/get-artifact"
import { useRestoreArtifactVersionMutation } from "@/features/artifacts/api/restore-artifact-version"
import { ArtifactEditDialog } from "@/features/artifacts/components/artifact-edit-dialog"
import { ArtifactPreviewFrame } from "@/features/artifacts/components/artifact-preview-frame"
import { ArtifactShareDialog } from "@/features/artifacts/components/artifact-share-dialog"
import { ArtifactSharesList } from "@/features/artifacts/components/artifact-shares-list"
import { artifactTypeLabel } from "@/features/artifacts/format"
import { ArtifactVersionSelector } from "@/features/artifacts/components/artifact-version-selector"
import { useActiveWorkspace } from "@/features/workspaces/components/use-active-workspace"
import { getErrorMessage } from "@/lib/api/errors"
import { formatDateTime } from "@/lib/format"

export function ArtifactDetail({ artifactId }: { artifactId: string }) {
  const { workspace } = useActiveWorkspace()
  const { data: artifact } = useArtifactQuery(artifactId)
  const [selectedVersionId, setSelectedVersionId] = useState(artifact.current_version_id)
  const [error, setError] = useState<string | null>(null)
  const restoreMutation = useRestoreArtifactVersionMutation()
  const contentQueries = useSuspenseQueries({
    queries: [
      artifactVersionContentQueryOptions(artifact.id, selectedVersionId),
      artifactVersionContentQueryOptions(artifact.id, artifact.current_version_id),
    ],
  })
  const selectedContent = contentQueries[0].data
  const currentContent = contentQueries[1].data
  const selectedVersion =
    artifact.versions.find((version) => version.id === selectedVersionId) ?? artifact.versions[0]
  const currentVersion = artifact.versions.find(
    (version) => version.id === artifact.current_version_id
  )
  const canWrite = workspace.current_user_role !== "read_only"
  const canManageShares =
    workspace.current_user_role === "owner" || workspace.current_user_role === "admin"

  async function handleRestore() {
    setError(null)
    try {
      const restored = await restoreMutation.mutateAsync({
        artifactId: artifact.id,
        versionId: selectedVersionId,
      })
      setSelectedVersionId(restored.current_version_id)
    } catch (restoreError) {
      setError(getErrorMessage(restoreError))
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <Link
        className="text-muted-foreground inline-flex w-fit items-center gap-1 text-sm hover:underline"
        to="/artifacts"
      >
        <ArrowLeftIcon className="size-4" />
        Artifacts
      </Link>
      <PageHeader
        actions={
          canWrite && selectedContent.content !== null ? (
            <ArtifactEditDialog
              artifactId={artifact.id}
              content={selectedContent.content}
              onUpdated={(updated) => {
                setSelectedVersionId(updated.current_version_id)
              }}
              title={artifact.title}
            />
          ) : null
        }
        description={`Updated ${formatDateTime(artifact.updated_at)} · ${String(artifact.versions.length)} versions`}
        title={artifact.title}
      />
      {error ? <p className="text-destructive text-sm">{error}</p> : null}
      <section className="grid gap-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <Badge variant="secondary">{artifactTypeLabel(artifact.artifact_type)}</Badge>
            {selectedVersion ? (
              <span className="text-muted-foreground text-xs">
                {formatDateTime(selectedVersion.created_at)}
              </span>
            ) : null}
          </div>
          <div className="flex items-center gap-2">
            <ArtifactVersionSelector
              currentVersionId={artifact.current_version_id}
              onValueChange={setSelectedVersionId}
              value={selectedVersionId}
              versions={artifact.versions}
            />
            {canWrite && selectedVersionId !== artifact.current_version_id ? (
              <Button
                disabled={restoreMutation.isPending}
                onClick={() => void handleRestore()}
                size="sm"
                type="button"
                variant="outline"
              >
                <RotateCcwIcon data-icon="inline-start" />
                {restoreMutation.isPending ? "Restoring…" : "Restore"}
              </Button>
            ) : null}
          </div>
        </div>
        <ArtifactPreviewFrame
          artifactType={artifact.artifact_type}
          content={selectedContent}
          title={`${artifact.title} preview`}
        />
      </section>
      {selectedVersionId !== artifact.current_version_id &&
      selectedContent.content !== null &&
      currentContent.content !== null ? (
        <section className="grid gap-3">
          <h2 className="font-heading text-lg font-medium">Changes From Current</h2>
          <RevisionDiff
            leftContent={currentContent.content}
            leftLabel="Current"
            rightContent={selectedContent.content}
            rightLabel={`Version ${String(selectedVersion?.revision_number ?? "")}`}
          />
        </section>
      ) : null}
      {canManageShares ? (
        <section className="grid gap-3 border-t pt-6">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 className="font-heading text-lg font-medium">Share Links</h2>
              <p className="text-muted-foreground mt-1 text-sm">
                Share links publish current version {String(currentVersion?.revision_number ?? "")}{" "}
                without exposing your workspace.
              </p>
              {selectedVersionId !== artifact.current_version_id ? (
                <p className="mt-1 text-xs text-amber-700 dark:text-amber-300">
                  You are viewing version {String(selectedVersion?.revision_number ?? "")}. A new
                  link will share the current version.
                </p>
              ) : null}
            </div>
            <ArtifactShareDialog
              artifactId={artifact.id}
              currentVersionNumber={currentVersion?.revision_number ?? artifact.versions.length}
            />
          </div>
          <Suspense fallback={<div className="bg-muted/30 h-20 animate-pulse rounded-lg" />}>
            <ArtifactSharesList artifactId={artifact.id} />
          </Suspense>
        </section>
      ) : null}
    </div>
  )
}
