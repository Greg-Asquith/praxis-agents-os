// apps/web/src/features/files/components/use-file-upload.ts

import { useCallback, useRef, useState } from "react"

import { useConfirmFileUploadMutation } from "@/features/files/api/confirm-file-upload"
import { useRequestFileUploadMutation } from "@/features/files/api/request-file-upload"
import { usePlatformUploadFileMutation } from "@/features/files/api/platform-upload-file"
import type { FileScope } from "@/features/files/types"
import { uploadFileDirectly } from "@/lib/api/direct-upload"
import { getErrorMessage } from "@/lib/api/errors"
import { contentTypeForWorkspaceFile } from "@/lib/file"
import { pluralize } from "@/lib/format"

type FileUploadProgress = {
  fileName: string
  fileNumber: number
  fileCount: number
  // Null when the transfer can't report progress (platform uploads).
  loadedBytes: number | null
  totalBytes: number
}

export type FileUpload = ReturnType<typeof useFileUpload>

function uploadedMessage(count: number, cancelled: boolean) {
  const uploaded = `${String(count)} ${pluralize(count, "file")} uploaded.`
  if (!cancelled) return uploaded
  return count > 0 ? `Upload cancelled. ${uploaded}` : "Upload cancelled."
}

export function useFileUpload({
  folderId = null,
  scope = "workspace",
}: {
  folderId?: string | null
  scope?: FileScope
}) {
  const requestUploadMutation = useRequestFileUploadMutation()
  const confirmUploadMutation = useConfirmFileUploadMutation()
  const platformUploadMutation = usePlatformUploadFileMutation()
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [progress, setProgress] = useState<FileUploadProgress | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const isUploading = progress !== null

  async function uploadFiles(files: Iterable<File> | null) {
    if (abortRef.current) return
    setError(null)
    setMessage(null)
    const pending = files ? Array.from(files) : []
    if (pending.length === 0) {
      return
    }

    const controller = new AbortController()
    abortRef.current = controller
    const measured = scope !== "platform"
    let uploadedCount = 0
    try {
      for (const [index, file] of pending.entries()) {
        if (controller.signal.aborted) break
        setProgress({
          fileName: file.name,
          fileNumber: index + 1,
          fileCount: pending.length,
          loadedBytes: measured ? 0 : null,
          totalBytes: file.size,
        })
        if (!measured) {
          await platformUploadMutation.mutateAsync(file)
          uploadedCount += 1
          continue
        }
        const result = await requestUploadMutation.mutateAsync({
          content_type: contentTypeForWorkspaceFile(file),
          filename: file.name,
          size_bytes: file.size,
          ...(folderId ? { allow_duplicate_content: true } : {}),
        })
        if (result.file) {
          uploadedCount += 1
          continue
        }
        if (!result.grant) {
          throw new Error("Upload grant was not returned.")
        }

        await uploadFileDirectly(
          result.grant.upload,
          file,
          result.grant.max_size_bytes,
          (fraction) => {
            setProgress((current) =>
              current ? { ...current, loadedBytes: Math.round(fraction * file.size) } : current
            )
          },
          controller.signal
        )
        await confirmUploadMutation.mutateAsync({
          uploadToken: result.grant.upload_token,
          folderId,
        })
        uploadedCount += 1
      }
      setMessage(uploadedMessage(uploadedCount, controller.signal.aborted))
    } catch (uploadError) {
      if (controller.signal.aborted) {
        setMessage(uploadedMessage(uploadedCount, true))
      } else {
        setError(getErrorMessage(uploadError))
      }
    } finally {
      abortRef.current = null
      setProgress(null)
    }
  }

  function cancel() {
    abortRef.current?.abort()
  }

  // Stable, so the status panel's auto-dismiss timer doesn't restart on every render.
  const dismiss = useCallback(() => {
    setError(null)
    setMessage(null)
  }, [])

  return { cancel, dismiss, error, isUploading, message, progress, uploadFiles }
}
