// apps/web/src/features/files/components/file-upload-button.ts

import { useId, useRef, useState } from "react"
import { UploadIcon } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { useConfirmFileUploadMutation } from "@/features/files/api/confirm-file-upload"
import { useRequestFileUploadMutation } from "@/features/files/api/request-file-upload"
import { uploadFileDirectly } from "@/lib/api/direct-upload"
import { getErrorMessage } from "@/lib/api/errors"
import { contentTypeForWorkspaceFile, workspaceFileAcceptValue } from "@/lib/file"

export function FileUploadButton() {
  const inputId = useId()
  const inputRef = useRef<HTMLInputElement | null>(null)
  const requestUploadMutation = useRequestFileUploadMutation()
  const confirmUploadMutation = useConfirmFileUploadMutation()
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const isUploading = requestUploadMutation.isPending || confirmUploadMutation.isPending

  async function handleFiles(files: FileList | null) {
    setError(null)
    setMessage(null)
    if (!files || files.length === 0) {
      return
    }

    const uploadedNames: string[] = []
    try {
      for (const file of Array.from(files)) {
        const result = await requestUploadMutation.mutateAsync({
          content_type: contentTypeForWorkspaceFile(file),
          filename: file.name,
          size_bytes: file.size,
        })
        if (result.file) {
          uploadedNames.push(result.file.name)
          continue
        }
        if (!result.grant) {
          throw new Error("Upload grant was not returned.")
        }

        await uploadFileDirectly(result.grant.upload, file, result.grant.max_size_bytes)
        const confirmed = await confirmUploadMutation.mutateAsync({
          uploadToken: result.grant.upload_token,
        })
        uploadedNames.push(confirmed.name)
      }
      setMessage(`${uploadedNames.join(", ")} uploaded.`)
    } catch (uploadError) {
      setError(getErrorMessage(uploadError))
    } finally {
      if (inputRef.current) {
        inputRef.current.value = ""
      }
    }
  }

  return (
    <div className="flex min-w-0 flex-col items-start gap-2 md:items-end">
      <input
        accept={workspaceFileAcceptValue()}
        aria-label="Choose files to upload"
        className="sr-only"
        id={inputId}
        multiple
        name="files"
        onChange={(event) => {
          void handleFiles(event.currentTarget.files)
        }}
        ref={inputRef}
        type="file"
      />
      <label className="sr-only" htmlFor={inputId}>
        Choose files to upload
      </label>
      <Button
        disabled={isUploading}
        onClick={() => {
          inputRef.current?.click()
        }}
        type="button"
      >
        <UploadIcon data-icon="inline-start" />
        {isUploading ? "Uploading" : "Upload files"}
      </Button>
      {error ? (
        <Alert className="max-w-sm" variant="destructive">
          <AlertTitle>Upload failed</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}
      {message ? (
        <p className="text-muted-foreground max-w-sm text-right text-xs">{message}</p>
      ) : null}
    </div>
  )
}
