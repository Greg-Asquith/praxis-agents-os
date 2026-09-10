// apps/web/src/features/files/components/copy-file-button.tsx

import { useState } from "react"
import { CopyIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { useCopyFileMutation } from "@/features/files/api/copy-file"
import type { WorkspaceFile } from "@/features/files/types"
import { getErrorMessage } from "@/lib/api/errors"

export function CopyFileButton({
  file,
  onCopied,
}: {
  file: WorkspaceFile
  onCopied: (file: WorkspaceFile) => void
}) {
  const mutation = useCopyFileMutation()
  const [requestId] = useState(() => crypto.randomUUID())
  const [error, setError] = useState<string | null>(null)

  async function handleCopy() {
    setError(null)
    try {
      onCopied(
        await mutation.mutateAsync({
          fileId: file.id,
          revisionId: file.current_revision_id,
          requestId,
        })
      )
    } catch (copyError) {
      setError(getErrorMessage(copyError))
    }
  }

  return (
    <div className="flex flex-col gap-2">
      <Button
        disabled={mutation.isPending}
        onClick={() => {
          void handleCopy()
        }}
        variant="outline"
      >
        <CopyIcon data-icon="inline-start" />
        {mutation.isPending ? "Copying" : "Make a workspace copy"}
      </Button>
      {error ? (
        <p role="alert" className="text-destructive text-sm">
          {error}
        </p>
      ) : null}
    </div>
  )
}
