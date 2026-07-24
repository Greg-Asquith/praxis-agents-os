// apps/web/src/features/knowledge/components/document-upload-button.tsx

import { useId, useRef, useState, type SyntheticEvent } from "react"
import { UploadIcon } from "lucide-react"

import { FormAlerts } from "@/components/forms/form-alerts"
import { Button } from "@/components/ui/button"
import { DialogClose, DialogFooter } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { confirmFileUpload } from "@/features/files/api/confirm-file-upload"
import { requestFileUpload } from "@/features/files/api/request-file-upload"
import { useCreateDocumentFromFileMutation } from "@/features/knowledge/api/create-document-from-file"
import { PrivacyField } from "@/features/knowledge/components/privacy-field"
import { uploadFileDirectly } from "@/lib/api/direct-upload"
import { getErrorMessage } from "@/lib/api/errors"
import { contentTypeForWorkspaceFile } from "@/lib/file"
import { formString } from "@/lib/forms"

const KNOWLEDGE_FILE_ACCEPT = [
  ".csv",
  ".docx",
  ".html",
  ".json",
  ".markdown",
  ".md",
  ".mdx",
  ".pdf",
  ".pptx",
  ".txt",
  ".xlsx",
].join(",")

export function DocumentUploadButton({ onSaved }: { onSaved: () => void }) {
  const inputId = useId()
  const inputRef = useRef<HTMLInputElement | null>(null)
  const mutation = useCreateDocumentFromFileMutation()
  const [file, setFile] = useState<File | null>(null)
  const [isPrivate, setIsPrivate] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)

  async function handleSubmit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!file) {
      setError("Choose a document to upload.")
      return
    }
    setError(null)
    setUploading(true)
    const title = formString(new FormData(event.currentTarget), "title").trim()
    let saved = false
    try {
      const upload = await requestFileUpload({
        content_type: contentTypeForWorkspaceFile(file),
        filename: file.name,
        size_bytes: file.size,
      })
      let fileId: string
      if (upload.file) {
        fileId = upload.file.id
      } else if (upload.grant) {
        await uploadFileDirectly(upload.grant.upload, file, upload.grant.max_size_bytes)
        const confirmed = await confirmFileUpload({ uploadToken: upload.grant.upload_token })
        fileId = confirmed.id
      } else {
        throw new Error("Upload grant was not returned.")
      }
      await mutation.mutateAsync({
        file_id: fileId,
        is_private: isPrivate,
        ...(title ? { title } : {}),
      })
      saved = true
    } catch (uploadError) {
      setError(getErrorMessage(uploadError))
    } finally {
      setUploading(false)
    }
    if (saved) {
      onSaved()
    }
  }

  const isPending = uploading || mutation.isPending

  return (
    <form className="flex flex-col gap-4" onSubmit={(event) => void handleSubmit(event)}>
      <FormAlerts error={error} errorTitle="Couldn’t upload document" validationEntries={[]} />
      <div className="grid gap-2">
        <Label htmlFor={inputId}>Document</Label>
        <input
          accept={KNOWLEDGE_FILE_ACCEPT}
          className="sr-only"
          id={inputId}
          onChange={(event) => {
            setFile(event.currentTarget.files?.[0] ?? null)
          }}
          ref={inputRef}
          type="file"
        />
        <Button
          onClick={() => {
            inputRef.current?.click()
          }}
          type="button"
          variant="outline"
        >
          <UploadIcon data-icon="inline-start" />
          {file?.name ?? "Choose Document"}
        </Button>
        <p className="text-muted-foreground text-xs">
          Upload text, PDF, Office, HTML, JSON, or CSV content.
        </p>
      </div>
      <div className="grid gap-2">
        <Label htmlFor="knowledge-upload-title">Title (optional)</Label>
        <Input autoComplete="off" id="knowledge-upload-title" maxLength={500} name="title" />
      </div>
      <PrivacyField checked={isPrivate} onCheckedChange={setIsPrivate} />
      <DialogFooter>
        <DialogClose render={<Button disabled={isPending} variant="outline" />}>Cancel</DialogClose>
        <Button disabled={isPending} type="submit">
          {isPending ? "Uploading…" : "Upload and Add"}
        </Button>
      </DialogFooter>
    </form>
  )
}
