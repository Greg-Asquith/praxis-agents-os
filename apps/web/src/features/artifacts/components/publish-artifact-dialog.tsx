// apps/web/src/features/artifacts/components/publish-artifact-dialog.tsx

import { useState } from "react"
import { useNavigate } from "@tanstack/react-router"
import { GlobeIcon } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { usePublishArtifactToPlatformMutation } from "@/features/artifacts/api/platform-create-artifact"
import { ArtifactPreviewFrame } from "@/features/artifacts/components/artifact-preview-frame"
import { artifactTypeLabel, describeArtifactSaveError } from "@/features/artifacts/format"
import type { Artifact, ArtifactContent, ArtifactVersion } from "@/features/artifacts/types"

export const PLATFORM_AUDIENCE_STATEMENT = "Available in every workspace on this deployment."

export function PublishArtifactDialog({
  artifact,
  content,
  version,
}: {
  artifact: Artifact
  content: ArtifactContent
  version: ArtifactVersion
}) {
  const mutation = usePublishArtifactToPlatformMutation()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [requestId, setRequestId] = useState(() => crypto.randomUUID())
  const [error, setError] = useState<string | null>(null)
  const isCurrent = version.id === artifact.current_version_id

  // One request ID per review so a retry after a network failure cannot publish twice.
  function handleOpenChange(nextOpen: boolean) {
    if (mutation.isPending) return
    setOpen(nextOpen)
    if (nextOpen) {
      setRequestId(crypto.randomUUID())
      setError(null)
    }
  }

  async function handlePublish() {
    setError(null)
    try {
      const created = await mutation.mutateAsync({
        artifactId: artifact.id,
        versionId: version.id,
        expectedCurrentVersionId: artifact.current_version_id,
        requestId,
      })
      setOpen(false)
      await navigate({
        to: "/artifacts/$artifactId",
        params: { artifactId: created.id },
        search: { platform: true },
      })
    } catch (publishError) {
      setError(describeArtifactSaveError(publishError))
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger render={<Button variant="outline" />}>
        <GlobeIcon data-icon="inline-start" />
        Publish to platform
      </DialogTrigger>
      <DialogContent className="max-h-[calc(100dvh-2rem)] overflow-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Publish to platform?</DialogTitle>
          <DialogDescription>
            A separate shared artifact is created from the version below. Later changes to this
            workspace artifact don’t affect it.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-4">
          <dl className="grid gap-3 rounded-lg border p-3 text-sm sm:grid-cols-3">
            <div className="sm:col-span-2">
              <dt className="text-muted-foreground text-xs">Title</dt>
              <dd className="mt-1 font-medium wrap-break-word">{artifact.title}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground text-xs">Version</dt>
              <dd className="mt-1 flex flex-wrap items-center gap-2">
                Version {String(version.revision_number)}
                <Badge variant={isCurrent ? "secondary" : "outline"}>
                  {isCurrent ? "Current" : "Earlier version"}
                </Badge>
              </dd>
            </div>
          </dl>
          <ArtifactPreviewFrame
            artifactType={artifact.artifact_type}
            content={content}
            title={`${artifact.title} preview`}
            versionId={version.id}
          />
          <Alert>
            <GlobeIcon />
            <AlertTitle>{PLATFORM_AUDIENCE_STATEMENT}</AlertTitle>
            <AlertDescription>
              Members of every workspace can view and open this{" "}
              {artifactTypeLabel(artifact.artifact_type)} artifact. Workspace editors can edit it,
              and each edit updates it everywhere.
            </AlertDescription>
          </Alert>
          {error ? (
            <p className="text-destructive text-sm" role="alert">
              {error}
            </p>
          ) : null}
        </div>
        <DialogFooter>
          <DialogClose render={<Button disabled={mutation.isPending} variant="outline" />}>
            Cancel
          </DialogClose>
          <Button disabled={mutation.isPending} onClick={() => void handlePublish()} type="button">
            <GlobeIcon data-icon="inline-start" />
            {mutation.isPending ? "Publishing…" : "Publish to platform"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
