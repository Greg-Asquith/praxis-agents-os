// apps/web/src/features/knowledge/components/document-upload-button.tsx

import { useEffect, useId, useRef, useState, type SyntheticEvent } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { UploadIcon } from "lucide-react"

import { FormAlerts } from "@/components/forms/form-alerts"
import { Button } from "@/components/ui/button"
import { DialogClose, DialogFooter } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { platformFileQueryOptions } from "@/features/files/api/platform-get-file"
import type { WorkspaceFile } from "@/features/files/types"
import { waitForPlatformKnowledgeUpload } from "@/features/knowledge/components/platform-knowledge-upload-state"
import { confirmFileUpload } from "@/features/files/api/confirm-file-upload"
import { usePlatformUploadFileMutation } from "@/features/files/api/platform-upload-file"
import { requestFileUpload } from "@/features/files/api/request-file-upload"
import { usePlatformCreateDocumentFromFileMutation } from "@/features/knowledge/api/platform-create-document-from-file"
import { useCreateDocumentFromFileMutation } from "@/features/knowledge/api/create-document-from-file"
import { PrivacyField } from "@/features/knowledge/components/privacy-field"
import { uploadFileDirectly } from "@/lib/api/direct-upload"
import { getErrorMessage } from "@/lib/api/errors"
import { contentTypeForWorkspaceFile } from "@/lib/file"
import { formString } from "@/lib/forms"

const KNOWLEDGE_FILE_ACCEPT = [
  ".csv",
  ".doc",
  ".docx",
  ".html",
  ".json",
  ".markdown",
  ".md",
  ".mdx",
  ".pdf",
  ".ppt",
  ".pptx",
  ".txt",
  ".xls",
  ".xlsx",
].join(",")

export function DocumentUploadButton({
  onSaved,
  platform = false,
}: {
  onSaved: () => void
  platform?: boolean
}) {
  const inputId = useId()
  const inputRef = useRef<HTMLInputElement | null>(null)
  const mutation = useCreateDocumentFromFileMutation()
  const platformCreate = usePlatformCreateDocumentFromFileMutation()
  const platformUpload = usePlatformUploadFileMutation(false)
  const [file, setFile] = useState<File | null>(null)
  const [isPrivate, setIsPrivate] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  const [uploadedFile, setUploadedFile] = useState<WorkspaceFile | null>(null)
  const queryClient = useQueryClient()
  const submissionRef = useRef<AbortController | null>(null)
  const [processing, setProcessing] = useState(false)

  useEffect(() => () => submissionRef.current?.abort(), [])

  async function handleSubmit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault()
    if (submissionRef.current) return
    if (!file) {
      setError("Choose a document to upload.")
      return
    }
    const controller = new AbortController()
    submissionRef.current = controller
    setError(null)
    setUploading(true)
    const title = formString(new FormData(event.currentTarget), "title").trim()
    let saved = false
    try {
      if (platform) {
        const uploaded = uploadedFile ?? (await platformUpload.mutateAsync(file))
        controller.signal.throwIfAborted()
        setUploadedFile(uploaded)
        setProcessing(true)
        await waitForPlatformKnowledgeUpload(
          uploaded,
          () => queryClient.fetchQuery(platformFileQueryOptions(uploaded.id)),
          controller.signal
        )
        controller.signal.throwIfAborted()
        setProcessing(false)
        await platformCreate.mutateAsync({
          file_id: uploaded.id,
          file_revision_id: uploaded.current_revision_id,
          ...(title ? { title } : {}),
        })
      } else {
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
      }
      saved = true
    } catch (uploadError) {
      if (!controller.signal.aborted) setError(getErrorMessage(uploadError))
    } finally {
      submissionRef.current = null
      if (!controller.signal.aborted) {
        setUploading(false)
        setProcessing(false)
      }
    }
    if (saved && !controller.signal.aborted) {
      onSaved()
    }
  }

  const isPending = uploading || mutation.isPending

  return (
    <form className="flex flex-col gap-4" onSubmit={(event) => void handleSubmit(event)}>
      <FormAlerts error={error} errorTitle="Couldn’t upload document" validationEntries={[]} />
      {processing ? (
        <p role="status" className="text-muted-foreground text-sm">
          Your file is processing. Keep this dialog open while it is added to Knowledge Base.
        </p>
      ) : null}
      <div className="grid gap-2">
        <Label htmlFor={inputId}>Document</Label>
        <input
          accept={KNOWLEDGE_FILE_ACCEPT}
          className="sr-only"
          disabled={isPending}
          id={inputId}
          onChange={(event) => {
            setFile(event.currentTarget.files?.[0] ?? null)
            setUploadedFile(null)
            setError(null)
            event.currentTarget.value = ""
          }}
          ref={inputRef}
          type="file"
        />
        <Button
          disabled={isPending}
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
      {platform ? (
        <p className="text-muted-foreground text-sm">
          Save a draft, then review and publish it to every workspace. The uploaded file stays
          unpublished.
        </p>
      ) : (
        <PrivacyField checked={isPrivate} onCheckedChange={setIsPrivate} />
      )}
      <DialogFooter>
        <DialogClose render={<Button disabled={isPending} variant="outline" />}>Cancel</DialogClose>
        <Button disabled={isPending} type="submit">
          {processing ? "Processing…" : isPending ? "Saving…" : "Upload and Add"}
        </Button>
      </DialogFooter>
    </form>
  )
}
