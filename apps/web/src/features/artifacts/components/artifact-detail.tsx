// apps/web/src/features/artifacts/components/artifact-detail.tsx

import { Suspense, useState } from "react"
import { useSuspenseQueries } from "@tanstack/react-query"
import { ArrowLeftIcon, ExternalLinkIcon, GlobeIcon } from "lucide-react"
import { Link } from "@tanstack/react-router"

import { PageHeader } from "@/components/shell/page-header"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { RevisionDiff } from "@/components/ui/revision-diff"
import { createArtifactViewUrl } from "@/features/artifacts/api/create-view-url"
import { artifactQueryOptions } from "@/features/artifacts/api/get-artifact"
import { artifactVersionContentQueryOptions } from "@/features/artifacts/api/get-artifact-version-content"
import { platformArtifactQueryOptions } from "@/features/artifacts/api/platform-get-artifact"
import { platformArtifactVersionContentQueryOptions } from "@/features/artifacts/api/platform-get-artifact-version-content"
import { ArtifactBadges } from "@/features/artifacts/components/artifact-badges"
import { ArtifactEditDialog } from "@/features/artifacts/components/artifact-edit-dialog"
import { ArtifactPreviewFrame } from "@/features/artifacts/components/artifact-preview-frame"
import { ArtifactRestoreButton } from "@/features/artifacts/components/artifact-restore-button"
import { ArtifactShareDialog } from "@/features/artifacts/components/artifact-share-dialog"
import { ArtifactSharesList } from "@/features/artifacts/components/artifact-shares-list"
import { ArtifactTypeTile } from "@/features/artifacts/components/artifact-type-tile"
import { ArtifactVersionSelector } from "@/features/artifacts/components/artifact-version-selector"
import { CopyArtifactButton } from "@/features/artifacts/components/copy-artifact-button"
import { PlatformArtifactActions } from "@/features/artifacts/components/platform-artifact-actions"
import { PublishArtifactDialog } from "@/features/artifacts/components/publish-artifact-dialog"
import { artifactTypeLabel, publicationLabel } from "@/features/artifacts/format"
import type { Artifact, PlatformArtifact } from "@/features/artifacts/types"
import { useActiveWorkspace } from "@/features/workspaces/components/use-active-workspace"
import { canEditWorkspace } from "@/features/workspaces/permissions"
import { getErrorMessage } from "@/lib/api/errors"
import { formatDateTime, pluralize } from "@/lib/format"
import { openSignedResource } from "@/lib/open-signed-resource"

export function ArtifactDetail({
  artifactId,
  isSuperAdmin = false,
  management = false,
  openEditor = false,
}: {
  artifactId: string
  isSuperAdmin?: boolean
  management?: boolean
  openEditor?: boolean
}) {
  const { workspace } = useActiveWorkspace()
  const detailOptions = management ? platformArtifactQueryOptions : artifactQueryOptions
  const contentOptions = management
    ? platformArtifactVersionContentQueryOptions
    : artifactVersionContentQueryOptions
  const [{ data: artifact }] = useSuspenseQueries({ queries: [detailOptions(artifactId)] })
  const [selectedVersionId, setSelectedVersionId] = useState(artifact.current_version_id)
  const [error, setError] = useState<string | null>(null)
  const [opening, setOpening] = useState(false)
  // A refetch can drop a version from view, so fall back before requesting its content.
  const selectedVersion =
    artifact.versions.find((version) => version.id === selectedVersionId) ?? artifact.versions[0]
  const activeVersionId = selectedVersion?.id ?? artifact.current_version_id
  const contentQueries = useSuspenseQueries({
    queries: [
      contentOptions(artifact.id, activeVersionId),
      contentOptions(artifact.id, artifact.current_version_id),
    ],
  })
  const selectedContent = contentQueries[0].data
  const currentContent = contentQueries[1].data
  const currentVersion = artifact.versions.find(
    (version) => version.id === artifact.current_version_id
  )
  const isPlatform = artifact.scope === "platform"
  const isCurrent = activeVersionId === artifact.current_version_id
  const editableContent = artifact.can_edit ? selectedContent.content : null
  const canCopy =
    isPlatform && artifact.is_published && canEditWorkspace(workspace.current_user_role)
  const canManageShares =
    !isPlatform &&
    (workspace.current_user_role === "owner" || workspace.current_user_role === "admin")
  const versionCount = artifact.versions.length

  async function handleOpen() {
    setError(null)
    setOpening(true)
    try {
      await openSignedResource(async () => {
        const grant = await createArtifactViewUrl(artifact.id, activeVersionId)
        return grant.url
      })
    } catch (openError) {
      setError(getErrorMessage(openError))
    } finally {
      setOpening(false)
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-2">
        <Link
          className="text-muted-foreground hover:text-foreground inline-flex w-fit items-center gap-1 text-sm transition-colors"
          search={isPlatform ? { scope: "platform" } : {}}
          to="/artifacts"
        >
          <ArrowLeftIcon className="size-3.5" />
          All artifacts
        </Link>
        <PageHeader
          actions={
            <div className="flex flex-wrap items-start gap-2 md:justify-end">
              {canCopy ? (
                <CopyArtifactButton
                  artifact={artifact}
                  key={`copy:${activeVersionId}`}
                  versionId={activeVersionId}
                />
              ) : null}
              {editableContent !== null ? (
                <ArtifactEditDialog
                  artifact={artifact}
                  content={editableContent}
                  defaultOpen={openEditor}
                  onSaved={(saved) => {
                    setSelectedVersionId(saved.current_version_id)
                  }}
                />
              ) : null}
              {!isPlatform &&
              isSuperAdmin &&
              selectedVersion &&
              selectedContent.content !== null ? (
                <PublishArtifactDialog
                  artifact={artifact}
                  content={selectedContent}
                  version={selectedVersion}
                />
              ) : null}
              {isPlatform && artifact.can_manage_platform ? (
                <PlatformArtifactActions
                  artifact={artifact}
                  currentVersionNumber={currentVersion?.revision_number ?? versionCount}
                />
              ) : null}
            </div>
          }
          description={
            <span className="flex flex-wrap items-center gap-2">
              <Badge variant="outline">{artifactTypeLabel(artifact.artifact_type)}</Badge>
              <ArtifactBadges artifact={artifact} />
              <span>
                Updated {formatDateTime(artifact.updated_at)} · {String(versionCount)}{" "}
                {pluralize(versionCount, "version")}
              </span>
            </span>
          }
          title={
            <span className="flex items-center gap-3">
              <ArtifactTypeTile type={artifact.artifact_type} />
              <span className="min-w-0 wrap-break-word">{artifact.title}</span>
            </span>
          }
        />
      </div>
      {isPlatform ? (
        <PlatformNotice artifact={artifact} canCopy={canCopy} workspaceName={workspace.name} />
      ) : null}
      {error ? <p className="text-destructive text-sm">{error}</p> : null}
      <section className="grid gap-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <ArtifactVersionSelector
              currentVersionId={artifact.current_version_id}
              onValueChange={setSelectedVersionId}
              value={activeVersionId}
              versions={artifact.versions}
            />
            {selectedVersion ? (
              <span className="text-muted-foreground text-xs">
                {formatDateTime(selectedVersion.created_at)}
              </span>
            ) : null}
          </div>
          <div className="flex items-center gap-2">
            {artifact.can_edit && selectedVersion && !isCurrent ? (
              <ArtifactRestoreButton
                artifact={artifact}
                onError={setError}
                onRestored={(restored) => {
                  setSelectedVersionId(restored.current_version_id)
                }}
                version={selectedVersion}
              />
            ) : null}
            {!isPlatform || artifact.is_published ? (
              <Button
                aria-label={`Open artifact ${artifact.title}`}
                disabled={opening}
                onClick={() => {
                  void handleOpen()
                }}
                size="sm"
                type="button"
                variant="outline"
              >
                <ExternalLinkIcon data-icon="inline-start" />
                {opening ? "Opening…" : "Open"}
              </Button>
            ) : null}
          </div>
        </div>
        <ArtifactPreviewFrame
          artifactType={artifact.artifact_type}
          content={selectedContent}
          title={`${artifact.title} preview`}
          versionId={activeVersionId}
        />
      </section>
      {!isCurrent && selectedContent.content !== null && currentContent.content !== null ? (
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
              {!isCurrent ? (
                <p className="mt-1 text-xs text-amber-700 dark:text-amber-300">
                  You are viewing version {String(selectedVersion?.revision_number ?? "")}. A new
                  link will share the current version.
                </p>
              ) : null}
            </div>
            <ArtifactShareDialog
              artifactId={artifact.id}
              currentVersionNumber={currentVersion?.revision_number ?? versionCount}
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

function PlatformNotice({
  artifact,
  canCopy,
  workspaceName,
}: {
  artifact: Artifact | PlatformArtifact
  canCopy: boolean
  workspaceName: string
}) {
  const publication = publicationLabel(artifact)
  if (publication) {
    return (
      <Alert>
        <GlobeIcon />
        <AlertTitle>
          {publication === "Withdrawn"
            ? "Withdrawn from every workspace"
            : "Not yet available in other workspaces"}
        </AlertTitle>
        <AlertDescription>
          Publish it to make the current version available in every workspace on this deployment.
        </AlertDescription>
      </Alert>
    )
  }
  return (
    <Alert>
      <GlobeIcon />
      <AlertTitle>Available in every workspace on this deployment</AlertTitle>
      <AlertDescription>
        {artifact.can_edit
          ? "Saving an edit or restoring a version updates it everywhere immediately."
          : "You can view and open this artifact. Ask a workspace editor to make a workspace copy for changes."}
        {canCopy ? ` Make a workspace copy for changes that stay in ${workspaceName}.` : null}
      </AlertDescription>
    </Alert>
  )
}
