// apps/web/src/features/artifacts/components/artifact-restore-button.tsx

import { useState } from "react"
import { RotateCcwIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { useRestorePlatformArtifactVersionMutation } from "@/features/artifacts/api/platform-restore-artifact-version"
import { useRestoreArtifactVersionMutation } from "@/features/artifacts/api/restore-artifact-version"
import { describeArtifactSaveError } from "@/features/artifacts/format"
import type { Artifact, ArtifactVersion } from "@/features/artifacts/types"

export function ArtifactRestoreButton({
  artifact,
  onError,
  onRestored,
  version,
}: {
  artifact: Artifact
  onError: (message: string | null) => void
  onRestored: (artifact: Artifact) => void
  version: ArtifactVersion
}) {
  const workspaceMutation = useRestoreArtifactVersionMutation()
  const platformMutation = useRestorePlatformArtifactVersionMutation()
  const [confirming, setConfirming] = useState(false)
  const isPlatform = artifact.scope === "platform"
  const pending = workspaceMutation.isPending || platformMutation.isPending
  const number = String(version.revision_number)

  async function restore() {
    onError(null)
    try {
      const restored = isPlatform
        ? await platformMutation.mutateAsync({
            artifactId: artifact.id,
            versionId: version.id,
            expectedCurrentVersionId: artifact.current_version_id,
          })
        : await workspaceMutation.mutateAsync({ artifactId: artifact.id, versionId: version.id })
      onRestored(restored)
    } catch (restoreError) {
      onError(describeArtifactSaveError(restoreError))
    }
    setConfirming(false)
  }

  return (
    <>
      <Button
        disabled={pending}
        onClick={() => {
          if (isPlatform) setConfirming(true)
          else void restore()
        }}
        size="sm"
        type="button"
        variant="outline"
      >
        <RotateCcwIcon data-icon="inline-start" />
        {pending ? "Restoring…" : "Restore"}
      </Button>
      {isPlatform ? (
        <ConfirmDialog
          confirmIcon={<RotateCcwIcon data-icon="inline-start" />}
          confirmLabel="Restore"
          confirmPendingLabel="Restoring"
          description={
            artifact.is_published
              ? `This creates a new version from version ${number} and makes it visible to every workspace immediately.`
              : `This creates a new version from version ${number}. It stays unavailable to other workspaces until you publish it.`
          }
          isPending={pending}
          onConfirm={restore}
          onOpenChange={setConfirming}
          open={confirming}
          title={`Restore version ${number}?`}
          variant="default"
        />
      ) : null}
    </>
  )
}
