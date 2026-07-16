// apps/web/src/features/skills/components/skill-documents-section.tsx

import { useState, type SyntheticEvent } from "react"
import { FileTextIcon, PlusIcon, Trash2Icon, UploadIcon } from "lucide-react"

import { FormSection } from "@/components/forms/form-section"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { EmptyState } from "@/components/ui/empty-state"
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import {
  createSkillDocumentDownload,
  useConfirmSkillDocumentUploadMutation,
  useCreateSkillDocumentUploadMutation,
  useDeleteSkillDocumentMutation,
  useSkillDocumentsQuery,
} from "@/features/skills/api/skill-documents"
import { SkillDocumentPreviewModal } from "@/features/skills/components/skill-document-preview-modal"
import { SkillDocumentsList } from "@/features/skills/components/skill-documents-list"
import type { SkillDocument } from "@/features/skills/types"
import { uploadFileDirectly } from "@/lib/api/direct-upload"
import { getErrorMessage } from "@/lib/api/errors"
import { contentTypeForFile } from "@/lib/file"

const DOCUMENT_NAME_PATTERN = /^[a-z0-9]+(_[a-z0-9]+)*$/

export function SkillDocumentsSection({ skillId }: { skillId: string }) {
  const { data } = useSkillDocumentsQuery(skillId)
  const createUploadMutation = useCreateSkillDocumentUploadMutation()
  const confirmUploadMutation = useConfirmSkillDocumentUploadMutation()
  const deleteDocumentMutation = useDeleteSkillDocumentMutation()
  const [documentName, setDocumentName] = useState("")
  const [file, setFile] = useState<File | null>(null)
  const [fileInputKey, setFileInputKey] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [documentToDelete, setDocumentToDelete] = useState<SkillDocument | null>(null)
  const [documentToPreview, setDocumentToPreview] = useState<SkillDocument | null>(null)
  const isUploading = createUploadMutation.isPending || confirmUploadMutation.isPending

  async function handleUpload(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setMessage(null)

    const normalizedName = documentName.trim()
    if (!DOCUMENT_NAME_PATTERN.test(normalizedName)) {
      setError("Use lowercase letters, numbers, and underscores (e.g. api_reference).")
      return
    }
    if (!file) {
      setError("Choose a document file.")
      return
    }

    try {
      const uploadGrant = await createUploadMutation.mutateAsync({
        skillId,
        payload: {
          content_type: contentTypeForFile(file),
          document_name: normalizedName,
          filename: file.name || normalizedName,
          size_bytes: file.size,
        },
      })
      await uploadFileDirectly(uploadGrant.upload, file, uploadGrant.max_size_bytes)
      const document = await confirmUploadMutation.mutateAsync({
        skillId,
        uploadToken: uploadGrant.upload_token,
      })
      setDocumentName("")
      setFile(null)
      setFileInputKey((current) => current + 1)
      if (document.status === "failed") {
        setMessage(`Uploaded, but conversion failed: ${document.error ?? "Unknown error."}`)
      } else {
        setMessage(`${document.name} uploaded.`)
      }
    } catch (uploadError) {
      setError(getErrorMessage(uploadError))
    }
  }

  async function handleDownload(document: SkillDocument) {
    setError(null)
    setMessage(null)

    try {
      const signed = await createSkillDocumentDownload(skillId, document.name)
      window.open(signed.url, "_blank", "noopener,noreferrer")
    } catch (downloadError) {
      setError(getErrorMessage(downloadError))
    }
  }

  async function confirmDeleteDocument() {
    if (!documentToDelete) {
      return
    }

    try {
      await deleteDocumentMutation.mutateAsync({
        documentName: documentToDelete.name,
        skillId,
      })
      setMessage(`${documentToDelete.name} deleted.`)
      setDocumentToDelete(null)
    } catch (deleteError) {
      setError(getErrorMessage(deleteError))
      setDocumentToDelete(null)
    }
  }

  return (
    <FormSection
      description="Manage the reference files agents can read after activating this skill."
      eyebrow="Documents"
      title="Reference documents"
    >
      <div className="flex flex-col gap-5">
        {error ? (
          <Alert variant="destructive">
            <AlertTitle>Document action failed</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        ) : null}
        {message ? (
          <Alert>
            <AlertTitle>Document updated</AlertTitle>
            <AlertDescription>{message}</AlertDescription>
          </Alert>
        ) : null}

        <form
          className="bg-muted/20 rounded-lg border p-4"
          onSubmit={(event) => {
            void handleUpload(event)
          }}
        >
          <FieldGroup className="grid gap-x-4 gap-y-3 lg:grid-cols-[minmax(12rem,0.8fr)_minmax(16rem,1.2fr)_auto] lg:items-start">
            <Field>
              <FieldLabel htmlFor="skill-document-name">Document name</FieldLabel>
              <Input
                id="skill-document-name"
                onChange={(event) => {
                  setDocumentName(event.currentTarget.value)
                }}
                placeholder="api_reference"
                value={documentName}
              />
              <FieldDescription>Lowercase name agents use to find this file.</FieldDescription>
            </Field>

            <Field>
              <FieldLabel htmlFor="skill-document-file">File</FieldLabel>
              <Input
                accept=".pdf,.docx,.txt,.md"
                id="skill-document-file"
                key={fileInputKey}
                onChange={(event) => {
                  setFile(event.currentTarget.files?.[0] ?? null)
                }}
                type="file"
              />
              <FieldDescription>{file ? file.name : "PDF, DOCX, TXT, or MD."}</FieldDescription>
            </Field>

            <Button className="w-full lg:mt-7 lg:w-auto" disabled={isUploading} type="submit">
              {isUploading ? (
                <>
                  <UploadIcon data-icon="inline-start" />
                  Uploading
                </>
              ) : (
                <>
                  <PlusIcon data-icon="inline-start" />
                  Upload
                </>
              )}
            </Button>
          </FieldGroup>
        </form>

        {data.documents.length === 0 ? (
          <EmptyState
            description="Upload reference documents the agent can read after activating this skill."
            icon={<FileTextIcon className="size-5" />}
            size="compact"
            title="No documents"
          />
        ) : (
          <SkillDocumentsList
            documents={data.documents}
            isDeleting={deleteDocumentMutation.isPending}
            onDelete={(document) => {
              setError(null)
              setMessage(null)
              setDocumentToDelete(document)
            }}
            onDownload={(document) => {
              void handleDownload(document)
            }}
            onPreview={setDocumentToPreview}
          />
        )}

        <SkillDocumentPreviewModal
          document={documentToPreview}
          onClose={() => {
            setDocumentToPreview(null)
          }}
          onDownload={(document) => {
            void handleDownload(document)
          }}
          skillId={skillId}
        />
        <ConfirmDialog
          confirmIcon={<Trash2Icon data-icon="inline-start" />}
          confirmLabel="Delete Document"
          confirmPendingLabel="Deleting"
          description={
            documentToDelete
              ? `This removes ${documentToDelete.name} from the skill reference documents.`
              : "This removes the selected reference document."
          }
          isPending={deleteDocumentMutation.isPending}
          onConfirm={confirmDeleteDocument}
          onOpenChange={(open) => {
            if (!open) {
              setDocumentToDelete(null)
            }
          }}
          open={documentToDelete !== null}
          title="Delete document?"
        />
      </div>
    </FormSection>
  )
}
