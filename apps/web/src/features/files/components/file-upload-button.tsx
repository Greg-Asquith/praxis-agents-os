// apps/web/src/features/files/components/file-upload-button.tsx

import { useId, useRef } from "react"
import { UploadIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import type { FileUpload } from "@/features/files/components/use-file-upload"
import { workspaceFileAcceptValue } from "@/lib/file"

export function FileUploadButton({ upload }: { upload: FileUpload }) {
  const inputId = useId()
  const inputRef = useRef<HTMLInputElement | null>(null)
  const { isUploading, uploadFiles } = upload

  async function handleFiles(files: FileList | null) {
    await uploadFiles(files)
    if (inputRef.current) {
      inputRef.current.value = ""
    }
  }

  return (
    <>
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
    </>
  )
}
