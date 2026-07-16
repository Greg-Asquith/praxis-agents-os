// apps/web/src/features/skills/components/pending-skill-documents-section.tsx

import { FileTextIcon, PlusIcon, Trash2Icon } from "lucide-react"
import type { Dispatch, SetStateAction } from "react"

import { FormSection } from "@/components/forms/form-section"
import { Button } from "@/components/ui/button"
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import type {
  PendingSkillDocumentDraft,
  PendingSkillDocumentUpload,
} from "@/features/skills/components/pending-skill-document-model"

const DOCUMENT_NAME_PATTERN = /^[a-z0-9]+(_[a-z0-9]+)*$/

export function PendingSkillDocumentsSection({
  documents,
  draft,
  onDocumentsChange,
  onDraftChange,
}: {
  documents: PendingSkillDocumentUpload[]
  draft: PendingSkillDocumentDraft
  onDocumentsChange: (documents: PendingSkillDocumentUpload[]) => void
  onDraftChange: Dispatch<SetStateAction<PendingSkillDocumentDraft>>
}) {
  function addDocument() {
    onDraftChange((current) => ({ ...current, error: null }))
    const normalizedName = draft.documentName.trim()

    if (!DOCUMENT_NAME_PATTERN.test(normalizedName)) {
      onDraftChange((current) => ({
        ...current,
        error: "Use lowercase letters, numbers, and underscores (e.g. api_reference).",
      }))
      return
    }
    if (!draft.file) {
      onDraftChange((current) => ({ ...current, error: "Choose a document file." }))
      return
    }
    if (documents.some((document) => document.documentName === normalizedName)) {
      onDraftChange((current) => ({
        ...current,
        error: "Each pending document needs a unique name.",
      }))
      return
    }

    onDocumentsChange([
      ...documents,
      {
        documentName: normalizedName,
        file: draft.file,
        id: `${normalizedName}:${String(draft.file.lastModified)}:${String(draft.file.size)}`,
      },
    ])
    onDraftChange((current) => ({
      documentName: "",
      error: null,
      file: null,
      fileInputKey: current.fileInputKey + 1,
    }))
  }

  function removeDocument(documentId: string) {
    onDocumentsChange(documents.filter((document) => document.id !== documentId))
  }

  return (
    <FormSection
      description="Optional — you can add documents any time after creating the skill."
      eyebrow="Documents"
      title="Reference documents"
    >
      <FieldGroup>
        <div className="bg-muted/20 grid gap-x-4 gap-y-3 rounded-lg border p-4 lg:grid-cols-[minmax(12rem,0.8fr)_minmax(16rem,1.2fr)_auto] lg:items-start">
          <Field>
            <FieldLabel htmlFor="pending-skill-document-name">Document name</FieldLabel>
            <Input
              id="pending-skill-document-name"
              onChange={(event) => {
                const documentName = event.currentTarget.value
                onDraftChange((current) => ({ ...current, documentName }))
              }}
              placeholder="api_reference"
              value={draft.documentName}
            />
            <FieldDescription>Lowercase name agents use to find this file.</FieldDescription>
          </Field>

          <Field>
            <FieldLabel htmlFor="pending-skill-document-file">File</FieldLabel>
            <Input
              accept=".pdf,.docx,.txt,.md"
              id="pending-skill-document-file"
              key={draft.fileInputKey}
              onChange={(event) => {
                const file = event.currentTarget.files?.[0] ?? null
                onDraftChange((current) => ({ ...current, file }))
              }}
              type="file"
            />
            <FieldDescription>
              {draft.file ? draft.file.name : "PDF, DOCX, TXT, or MD."}
            </FieldDescription>
          </Field>

          <Button
            className="w-full lg:mt-7 lg:w-auto"
            onClick={addDocument}
            type="button"
            variant="outline"
          >
            <PlusIcon data-icon="inline-start" />
            Add
          </Button>
        </div>

        {draft.error ? <p className="text-destructive text-sm">{draft.error}</p> : null}

        <div className="flex flex-col gap-2">
          {documents.length === 0 ? (
            <p className="bg-muted/30 text-muted-foreground rounded-lg p-3 text-sm">
              No documents selected for upload.
            </p>
          ) : (
            documents.map((document) => (
              <div
                className="flex min-w-0 items-center justify-between gap-3 rounded-md border p-3"
                key={document.id}
              >
                <div className="flex min-w-0 items-center gap-3">
                  <FileTextIcon className="text-muted-foreground size-4 shrink-0" />
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium">{document.documentName}</p>
                    <p className="text-muted-foreground truncate text-xs">{document.file.name}</p>
                  </div>
                </div>
                <Button
                  aria-label={`Remove ${document.documentName}`}
                  onClick={() => {
                    removeDocument(document.id)
                  }}
                  size="icon-sm"
                  type="button"
                  variant="outline"
                >
                  <Trash2Icon />
                </Button>
              </div>
            ))
          )}
        </div>
      </FieldGroup>
    </FormSection>
  )
}
