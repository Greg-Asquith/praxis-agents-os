// apps/web/src/features/skills/components/skill-form.tsx

import { useId, useMemo, useState, type ReactNode, type SyntheticEvent } from "react"
import { Link } from "@tanstack/react-router"
import { CheckIcon, FileTextIcon, PlusIcon, SaveIcon, Trash2Icon } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Field, FieldDescription, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import {
  buildSkillPayload,
  initialSkillFormState,
  isSkillFormDirty,
  validateSkillFormState,
  type SkillFormState,
} from "@/features/skills/components/skill-form-model"
import { SkillFormSection } from "@/features/skills/components/skill-form-section"
import type { Skill, SkillCreateRequest, SkillUpdateRequest } from "@/features/skills/types"
import { getErrorMessage } from "@/lib/api/errors"
import { buildFieldErrors } from "@/lib/forms"

const DOCUMENT_NAME_PATTERN = /^[a-z0-9]+(_[a-z0-9]+)*$/

export type PendingSkillDocumentUpload = {
  documentName: string
  file: File
  id: string
}

type SkillFormProps =
  | {
      cancelLabel: string
      children?: ReactNode
      isSubmitting: boolean
      mode: "create"
      onSubmit: (
        payload: SkillCreateRequest,
        documents: PendingSkillDocumentUpload[]
      ) => Promise<void>
    }
  | {
      cancelLabel: string
      children?: ReactNode
      isSubmitting: boolean
      mode: "edit"
      onChange?: () => void
      onSubmit: (payload: SkillUpdateRequest) => Promise<void>
      skill: Skill
    }

export function SkillForm(props: SkillFormProps) {
  const formId = useId()
  const skill = props.mode === "edit" ? props.skill : null
  const initialState = useMemo(() => initialSkillFormState(skill), [skill])
  const [state, setState] = useState<SkillFormState>(() => initialState)
  const [formError, setFormError] = useState<string | null>(null)
  const [showValidation, setShowValidation] = useState(false)
  const [pendingDocuments, setPendingDocuments] = useState<PendingSkillDocumentUpload[]>([])
  const validationEntries = useMemo(
    () => (showValidation ? validateSkillFormState(state) : []),
    [showValidation, state]
  )
  const fieldErrors = useMemo(() => buildFieldErrors(validationEntries), [validationEntries])
  const isDirty = props.mode === "edit" ? isSkillFormDirty(state, initialState) : true

  function setField<K extends keyof SkillFormState>(field: K, value: SkillFormState[K]) {
    if (props.mode === "edit") {
      props.onChange?.()
    }
    setState((current) => ({ ...current, [field]: value }))
  }

  async function handleSubmit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault()
    setFormError(null)

    const nextValidationEntries = validateSkillFormState(state)
    if (nextValidationEntries.length > 0) {
      setShowValidation(true)
      return
    }

    setShowValidation(false)

    try {
      if (props.mode === "create") {
        const payload = buildSkillPayload(state, "create")
        if (typeof payload === "string") {
          setFormError(payload)
          return
        }
        await props.onSubmit(payload, pendingDocuments)
      } else {
        const payload = buildSkillPayload(state, "edit")
        if (typeof payload === "string") {
          setFormError(payload)
          return
        }
        await props.onSubmit(payload)
      }
    } catch (error) {
      setFormError(getErrorMessage(error))
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <form
        className="flex flex-col gap-4"
        id={formId}
        noValidate
        onSubmit={(event) => {
          void handleSubmit(event)
        }}
      >
        {formError ? (
          <Alert variant="destructive">
            <AlertTitle>Skill not saved</AlertTitle>
            <AlertDescription>{formError}</AlertDescription>
          </Alert>
        ) : null}

        {validationEntries.length > 0 ? (
          <Alert variant="destructive">
            <AlertTitle>Review required fields</AlertTitle>
            <AlertDescription>
              <ul className="flex list-disc flex-col gap-1 pl-4">
                {validationEntries.map((entry) => (
                  <li key={entry.fieldId}>
                    <a href={`#${entry.fieldId}`}>{entry.label}</a>: {entry.message}
                  </li>
                ))}
              </ul>
            </AlertDescription>
          </Alert>
        ) : null}

        <SkillFormSection
          description="Define the compact catalog entry agents see before they activate this skill."
          eyebrow="Identity"
          title="Skill identity"
        >
          <FieldGroup>
            <Field data-invalid={fieldErrors["skill-name"] ? true : undefined}>
              <FieldLabel htmlFor="skill-name">Name</FieldLabel>
              <Input
                aria-invalid={fieldErrors["skill-name"] ? true : undefined}
                className="scroll-mt-20"
                id="skill-name"
                maxLength={255}
                onChange={(event) => {
                  setField("name", event.currentTarget.value)
                }}
                required
                value={state.name}
              />
              <FieldDescription>
                Human-readable name for this skill. The agent identifier is generated from it when
                saved.
              </FieldDescription>
              <FieldError>{fieldErrors["skill-name"]}</FieldError>
            </Field>

            <Field data-invalid={fieldErrors["skill-description"] ? true : undefined}>
              <FieldLabel htmlFor="skill-description">Description</FieldLabel>
              <Textarea
                aria-invalid={fieldErrors["skill-description"] ? true : undefined}
                className="min-h-28 scroll-mt-20"
                id="skill-description"
                maxLength={1024}
                onChange={(event) => {
                  setField("description", event.currentTarget.value)
                }}
                required
                value={state.description}
              />
              <FieldDescription>
                Always visible to the agent - it decides when to activate this skill from the name
                and description alone. Say what the skill does and when to use it.
              </FieldDescription>
              <FieldError>{fieldErrors["skill-description"]}</FieldError>
            </Field>
          </FieldGroup>
        </SkillFormSection>

        <SkillFormSection
          description="Write the runbook that loads only after the agent activates this skill."
          eyebrow="Instructions"
          title="Activation instructions"
        >
          <FieldGroup>
            <Field data-invalid={fieldErrors["skill-instructions"] ? true : undefined}>
              <FieldLabel htmlFor="skill-instructions">Instructions</FieldLabel>
              <Textarea
                aria-invalid={fieldErrors["skill-instructions"] ? true : undefined}
                className="min-h-80 scroll-mt-20"
                id="skill-instructions"
                onChange={(event) => {
                  setField("instructions", event.currentTarget.value)
                }}
                required
                value={state.instructions}
              />
              <FieldDescription>
                Loaded only when the agent activates the skill. Keep the description above
                self-sufficient.
              </FieldDescription>
              <FieldError>{fieldErrors["skill-instructions"]}</FieldError>
            </Field>
          </FieldGroup>
        </SkillFormSection>

        {props.mode === "create" ? (
          <PendingSkillDocumentsSection
            documents={pendingDocuments}
            onDocumentsChange={setPendingDocuments}
          />
        ) : null}

        <SkillFormSection
          description="Control whether the skill is assignable and easy to find."
          eyebrow="State"
          title="Availability"
        >
          <FieldGroup className="grid gap-5 sm:grid-cols-2">
            <Field>
              <FieldLabel htmlFor="skill-active">Status</FieldLabel>
              <Select
                onValueChange={(value) => {
                  setField("isActive", value === "false" ? "false" : "true")
                }}
                value={state.isActive}
              >
                <SelectTrigger id="skill-active" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent align="start">
                  <SelectGroup>
                    <SelectItem value="true">Active</SelectItem>
                    <SelectItem value="false">Inactive</SelectItem>
                  </SelectGroup>
                </SelectContent>
              </Select>
            </Field>

            <Field>
              <FieldLabel htmlFor="skill-favorite">Favorite</FieldLabel>
              <Select
                onValueChange={(value) => {
                  setField("isFavorite", value === "true" ? "true" : "false")
                }}
                value={state.isFavorite}
              >
                <SelectTrigger id="skill-favorite" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent align="start">
                  <SelectGroup>
                    <SelectItem value="false">No</SelectItem>
                    <SelectItem value="true">Yes</SelectItem>
                  </SelectGroup>
                </SelectContent>
              </Select>
            </Field>
          </FieldGroup>
        </SkillFormSection>
      </form>

      {props.children}

      <div className="bg-background/95 sticky -bottom-6 z-10 -mx-4 border-t px-4 py-3 shadow-[0_-12px_32px_rgba(15,23,42,0.08)] backdrop-blur md:-mx-6 md:px-6">
        <div className="mx-auto flex max-w-5xl flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-muted-foreground text-sm">
            {props.mode === "edit"
              ? isDirty
                ? "Unsaved changes"
                : "No unsaved changes"
              : "Ready to create when required fields are complete"}
          </p>
          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <Button
              className="w-full sm:w-auto"
              disabled={props.isSubmitting}
              render={<Link to="/skills" />}
              type="button"
              variant="outline"
            >
              {props.cancelLabel}
            </Button>
            <Button
              className="w-full sm:w-auto"
              disabled={props.isSubmitting || (props.mode === "edit" && !isDirty)}
              form={formId}
              type="submit"
            >
              {props.isSubmitting ? (
                <>
                  <SaveIcon data-icon="inline-start" />
                  {props.mode === "create" ? "Creating" : "Saving"}
                </>
              ) : (
                <>
                  <CheckIcon data-icon="inline-start" />
                  {props.mode === "create" ? "Create Skill" : "Save Changes"}
                </>
              )}
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}

function PendingSkillDocumentsSection({
  documents,
  onDocumentsChange,
}: {
  documents: PendingSkillDocumentUpload[]
  onDocumentsChange: (documents: PendingSkillDocumentUpload[]) => void
}) {
  const [documentName, setDocumentName] = useState("")
  const [file, setFile] = useState<File | null>(null)
  const [fileInputKey, setFileInputKey] = useState(0)
  const [error, setError] = useState<string | null>(null)

  function addDocument() {
    setError(null)
    const normalizedName = documentName.trim()

    if (!DOCUMENT_NAME_PATTERN.test(normalizedName)) {
      setError("Use lowercase letters, numbers, and underscores (e.g. api_reference).")
      return
    }
    if (!file) {
      setError("Choose a document file.")
      return
    }
    if (documents.some((document) => document.documentName === normalizedName)) {
      setError("Each pending document needs a unique name.")
      return
    }

    onDocumentsChange([
      ...documents,
      {
        documentName: normalizedName,
        file,
        id: `${normalizedName}:${String(file.lastModified)}:${String(file.size)}`,
      },
    ])
    setDocumentName("")
    setFile(null)
    setFileInputKey((current) => current + 1)
  }

  function removeDocument(documentId: string) {
    onDocumentsChange(documents.filter((document) => document.id !== documentId))
  }

  return (
    <SkillFormSection
      description="Add reference files now; they upload after the skill is created."
      eyebrow="Documents"
      title="Reference documents"
    >
      <FieldGroup>
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)_auto] lg:items-end">
          <Field>
            <FieldLabel htmlFor="pending-skill-document-name">Document name</FieldLabel>
            <Input
              id="pending-skill-document-name"
              onChange={(event) => {
                setDocumentName(event.currentTarget.value)
              }}
              placeholder="api_reference"
              value={documentName}
            />
            <FieldDescription>Semantic name the agent uses, e.g. api_reference.</FieldDescription>
          </Field>

          <Field>
            <FieldLabel htmlFor="pending-skill-document-file">File</FieldLabel>
            <Input
              accept=".pdf,.docx,.txt,.md"
              id="pending-skill-document-file"
              key={fileInputKey}
              onChange={(event) => {
                setFile(event.currentTarget.files?.[0] ?? null)
              }}
              type="file"
            />
            <FieldDescription>{file ? file.name : "PDF, DOCX, TXT, or MD."}</FieldDescription>
          </Field>

          <Button onClick={addDocument} type="button" variant="outline">
            <PlusIcon data-icon="inline-start" />
            Add
          </Button>
        </div>

        {error ? <p className="text-destructive text-sm">{error}</p> : null}

        <div className="flex flex-col gap-2">
          {documents.length === 0 ? (
            <p className="text-muted-foreground rounded-md border border-dashed p-3 text-sm">
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
    </SkillFormSection>
  )
}
