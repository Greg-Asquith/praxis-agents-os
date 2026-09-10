// apps/web/src/features/files/components/use-file-upload.ts

import { useState } from "react"

import { useConfirmFileUploadMutation } from "@/features/files/api/confirm-file-upload"
import { useRequestFileUploadMutation } from "@/features/files/api/request-file-upload"
import { usePlatformUploadFileMutation } from "@/features/files/api/platform-upload-file"
import type { FileScope } from "@/features/files/types"
import { uploadFileDirectly } from "@/lib/api/direct-upload"
import { getErrorMessage } from "@/lib/api/errors"
import { contentTypeForWorkspaceFile } from "@/lib/file"

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
  const [isUploading, setIsUploading] = useState(false)

  async function uploadFiles(files: Iterable<File> | null) {
    if (isUploading) return
    setError(null)
    setMessage(null)
    const pending = files ? Array.from(files) : []
    if (pending.length === 0) {
      return
    }

    setIsUploading(true)
    let uploadedCount = 0
    try {
      for (const file of pending) {
        if (scope === "platform") {
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

        await uploadFileDirectly(result.grant.upload, file, result.grant.max_size_bytes)
        await confirmUploadMutation.mutateAsync({
          uploadToken: result.grant.upload_token,
          folderId,
        })
        uploadedCount += 1
      }
      setMessage(`${String(uploadedCount)} ${uploadedCount === 1 ? "file" : "files"} uploaded.`)
    } catch (uploadError) {
      setError(getErrorMessage(uploadError))
    } finally {
      setIsUploading(false)
    }
  }

  return { error, isUploading, message, uploadFiles }
}
