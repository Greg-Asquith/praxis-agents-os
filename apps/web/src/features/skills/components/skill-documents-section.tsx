// apps/web/src/features/skills/components/skill-documents-section.tsx

import { useState, type SyntheticEvent } from "react"
import { DownloadIcon, FileTextIcon, PlusIcon, Trash2Icon, UploadIcon } from "lucide-react"

import { FormSection } from "@/components/forms/form-section"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { EmptyState } from "@/components/ui/empty-state"
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import {
  ResponsiveList,
  ResponsiveListItem,
  ResponsiveListMeta,
} from "@/components/ui/responsive-list"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import {
  createSkillDocumentDownload,
  useConfirmSkillDocumentUploadMutation,
  useCreateSkillDocumentUploadMutation,
  useDeleteSkillDocumentMutation,
  useSkillDocumentsQuery,
} from "@/features/skills/api/skill-documents"
import type { SkillDocument } from "@/features/skills/types"
import { uploadFileDirectly } from "@/lib/api/direct-upload"
import { getErrorMessage } from "@/lib/api/errors"
import { contentTypeForFile } from "@/lib/file"
import { formatBytes, formatDateTime } from "@/lib/format"

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

  function handleDelete(document: SkillDocument) {
    setError(null)
    setMessage(null)
    setDocumentToDelete(document)
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
          className="rounded-md border p-3"
          onSubmit={(event) => {
            void handleUpload(event)
          }}
        >
          <FieldGroup className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)_auto] lg:items-end">
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
              <FieldDescription>Semantic name the agent uses, e.g. api_reference.</FieldDescription>
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

            <Button disabled={isUploading} type="submit">
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
          <DocumentsList
            documents={data.documents}
            isDeleting={deleteDocumentMutation.isPending}
            onDelete={(document) => {
              handleDelete(document)
            }}
            onDownload={(document) => {
              void handleDownload(document)
            }}
          />
        )}
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

function DocumentsList({
  documents,
  isDeleting,
  onDelete,
  onDownload,
}: {
  documents: SkillDocument[]
  isDeleting: boolean
  onDelete: (document: SkillDocument) => void
  onDownload: (document: SkillDocument) => void
}) {
  return (
    <div className="flex flex-col gap-3">
      <ResponsiveList>
        {documents.map((document) => (
          <DocumentMobileRow
            document={document}
            isDeleting={isDeleting}
            key={document.name}
            onDelete={onDelete}
            onDownload={onDownload}
          />
        ))}
      </ResponsiveList>

      <div className="hidden md:block">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>File</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Size</TableHead>
              <TableHead>Updated</TableHead>
              <TableHead>
                <span className="sr-only">Actions</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {documents.map((document) => (
              <TableRow key={document.name}>
                <TableCell className="font-medium">{document.name}</TableCell>
                <TableCell>
                  <span className="text-muted-foreground block max-w-xs truncate text-sm">
                    {document.filename}
                  </span>
                </TableCell>
                <TableCell>
                  <DocumentStatusBadge document={document} />
                </TableCell>
                <TableCell>{formatBytes(document.size_bytes)}</TableCell>
                <TableCell>{formatDateTime(document.updated_at)}</TableCell>
                <TableCell>
                  <div className="flex justify-end gap-2">
                    <Button
                      onClick={() => {
                        onDownload(document)
                      }}
                      size="sm"
                      type="button"
                      variant="outline"
                    >
                      <DownloadIcon data-icon="inline-start" />
                      Download
                    </Button>
                    <Button
                      disabled={isDeleting}
                      onClick={() => {
                        onDelete(document)
                      }}
                      size="icon-sm"
                      type="button"
                      variant="outline"
                      aria-label={`Delete ${document.name}`}
                    >
                      <Trash2Icon />
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}

function DocumentMobileRow({
  document,
  isDeleting,
  onDelete,
  onDownload,
}: {
  document: SkillDocument
  isDeleting: boolean
  onDelete: (document: SkillDocument) => void
  onDownload: (document: SkillDocument) => void
}) {
  return (
    <ResponsiveListItem>
      <div className="flex min-w-0 flex-col gap-3">
        <div className="flex min-w-0 items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="truncate font-medium">{document.name}</p>
            <p className="text-muted-foreground truncate text-xs">{document.filename}</p>
          </div>
          <DocumentStatusBadge document={document} />
        </div>

        <dl className="grid gap-3 sm:grid-cols-2">
          <ResponsiveListMeta label="Size">{formatBytes(document.size_bytes)}</ResponsiveListMeta>
          <ResponsiveListMeta label="Updated">
            {formatDateTime(document.updated_at)}
          </ResponsiveListMeta>
        </dl>

        <div className="grid gap-2 sm:grid-cols-2">
          <Button
            onClick={() => {
              onDownload(document)
            }}
            type="button"
            variant="outline"
          >
            <DownloadIcon data-icon="inline-start" />
            Download
          </Button>
          <Button
            disabled={isDeleting}
            onClick={() => {
              onDelete(document)
            }}
            type="button"
            variant="outline"
          >
            <Trash2Icon data-icon="inline-start" />
            Delete
          </Button>
        </div>
      </div>
    </ResponsiveListItem>
  )
}

function DocumentStatusBadge({ document }: { document: SkillDocument }) {
  return (
    <Badge
      title={document.status === "failed" ? (document.error ?? "Conversion failed") : undefined}
      variant={document.status === "ready" ? "default" : "destructive"}
    >
      {document.status === "ready" ? "Ready" : "Failed"}
    </Badge>
  )
}
