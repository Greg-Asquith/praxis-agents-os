// apps/web/src/features/files/components/file-upload-button.tsx

import { useId, useRef } from "react"
import { UploadIcon } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { useFileUpload } from "@/features/files/components/use-file-upload"
import type { FileScope } from "@/features/files/types"
import { workspaceFileAcceptValue } from "@/lib/file"

export function FileUploadButton({
  folderId = null,
  scope = "workspace",
}: {
  folderId?: string | null
  scope?: FileScope
}) {
  const inputId = useId()
  const inputRef = useRef<HTMLInputElement | null>(null)
  const { error, isUploading, message, uploadFiles } = useFileUpload({ folderId, scope })

  async function handleFiles(files: FileList | null) {
    await uploadFiles(files)
    if (inputRef.current) {
      inputRef.current.value = ""
    }
  }

  return (
    <div className="flex max-w-full min-w-0 flex-col items-start gap-2 self-start md:items-end">
      <input
        accept={workspaceFileAcceptValue()}
        aria-label="Choose Files to Upload"
        className="sr-only"
        disabled={isUploading}
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
        Choose Files to Upload
      </label>
      <Button
        disabled={isUploading}
        onClick={() => {
          inputRef.current?.click()
        }}
        type="button"
      >
        <UploadIcon data-icon="inline-start" />
        {isUploading ? "Uploading" : "Upload Files"}
      </Button>
      {error ? (
        <Alert className="w-64 max-w-full wrap-anywhere" variant="destructive">
          <AlertTitle>Upload failed</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}
      {message ? (
        <p
          role="status"
          className="text-muted-foreground max-w-40 text-xs wrap-anywhere md:text-right"
        >
          {message}
        </p>
      ) : null}
    </div>
  )
}
