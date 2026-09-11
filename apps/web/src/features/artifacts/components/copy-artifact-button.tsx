// apps/web/src/features/artifacts/components/copy-artifact-button.tsx

import { useState } from "react"
import { useNavigate } from "@tanstack/react-router"
import { CopyIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { useCopyArtifactMutation } from "@/features/artifacts/api/copy-artifact"
import type { Artifact } from "@/features/artifacts/types"
import { getErrorMessage } from "@/lib/api/errors"

export function CopyArtifactButton({
  artifact,
  versionId,
}: {
  artifact: Artifact
  versionId: string
}) {
  const mutation = useCopyArtifactMutation()
  const navigate = useNavigate()
  // The request ID survives retries so a repeated click cannot create two copies.
  const [requestId] = useState(() => crypto.randomUUID())
  const [error, setError] = useState<string | null>(null)

  async function handleCopy() {
    setError(null)
    try {
      const copy = await mutation.mutateAsync({ artifactId: artifact.id, versionId, requestId })
      await navigate({
        to: "/artifacts/$artifactId",
        params: { artifactId: copy.id },
        search: { edit: true },
      })
    } catch (copyError) {
      setError(getErrorMessage(copyError))
    }
  }

  return (
    <div className="flex flex-col items-end gap-1">
      <Button
        disabled={mutation.isPending}
        onClick={() => {
          void handleCopy()
        }}
        type="button"
        variant="outline"
      >
        <CopyIcon data-icon="inline-start" />
        {mutation.isPending ? "Copying…" : "Make a workspace copy"}
      </Button>
      {error ? (
        <p className="text-destructive text-xs" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  )
}
