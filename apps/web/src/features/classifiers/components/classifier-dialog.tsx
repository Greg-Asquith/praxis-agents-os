// apps/web/src/features/classifiers/components/classifier-dialog.tsx

import { useMemo, useState, type SyntheticEvent } from "react"
import { ChevronDownIcon, PlusIcon, Trash2Icon } from "lucide-react"

import { FormAlerts } from "@/components/forms/form-alerts"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  Field,
  FieldDescription,
  FieldError,
  FieldGroup,
  FieldLabel,
  FieldLegend,
  FieldSet,
} from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"
import {
  AUTOMATIC_CLASSIFIER_MODEL,
  MAX_CLASSIFIER_LABELS,
  buildClassifierModelOptions,
  buildClassifierPayload,
  classifierIdentifierFromName,
  classifierLabelDescriptionFieldId,
  classifierLabelFieldId,
  initialClassifierFormState,
  validateClassifierFormState,
  type ClassifierFormState,
  type ClassifierLabelDraft,
} from "@/features/classifiers/components/classifier-form-model"
import type { Classifier, ClassifierCreateRequest } from "@/features/classifiers/types"
import type { ModelCatalogResponse } from "@/features/models/types"
import { getErrorMessage } from "@/lib/api/errors"
import { buildFieldErrors } from "@/lib/forms"

type ClassifierDialogProps = {
  classifier: Classifier | null
  isPending: boolean
  modelCatalog: ModelCatalogResponse
  onOpenChange: (open: boolean) => void
  onSubmit: (payload: ClassifierCreateRequest) => Promise<Classifier>
  open: boolean
}

export function ClassifierDialog({
  classifier,
  isPending,
  modelCatalog,
  onOpenChange,
  onSubmit,
  open,
}: ClassifierDialogProps) {
  const mode = classifier ? "edit" : "create"
  const [state, setState] = useState<ClassifierFormState>(() =>
    initialClassifierFormState(classifier)
  )
  const [formError, setFormError] = useState<string | null>(null)
  const [showValidation, setShowValidation] = useState(false)
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const validationEntries = useMemo(() => validateClassifierFormState(state), [state])
  const visibleValidationEntries = showValidation ? validationEntries : []
  const fieldErrors = buildFieldErrors(visibleValidationEntries)
  const modelOptions = useMemo(
    () => buildClassifierModelOptions(modelCatalog, classifier),
    [classifier, modelCatalog]
  )

  function setField<K extends keyof ClassifierFormState>(field: K, value: ClassifierFormState[K]) {
    setState((current) => ({ ...current, [field]: value }))
  }

  function setDisplayName(displayName: string) {
    setState((current) => ({
      ...current,
      displayName,
      name: mode === "create" ? classifierIdentifierFromName(displayName) : current.name,
    }))
  }

  function addLabel() {
    setState((current) => ({
      ...current,
      labels: [
        ...current.labels,
        {
          description: "",
          key: Math.max(-1, ...current.labels.map((label) => label.key)) + 1,
          label: "",
        },
      ],
    }))
  }

  function updateLabel(key: number, field: "description" | "label", value: string) {
    setState((current) => ({
      ...current,
      labels: current.labels.map((label) =>
        label.key === key ? { ...label, [field]: value } : label
      ),
    }))
  }

  function removeLabel(key: number) {
    setState((current) => ({
      ...current,
      labels: current.labels.filter((label) => label.key !== key),
    }))
  }

  async function handleSubmit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault()
    setFormError(null)
    setShowValidation(true)
    const payload = buildClassifierPayload(state)
    if (typeof payload === "string") {
      if (
        validationEntries.some(
          (entry) => entry.fieldId === "classifier-name" || entry.fieldId === "classifier-model"
        )
      ) {
        setAdvancedOpen(true)
      }
      return
    }
    try {
      await onSubmit(payload)
      onOpenChange(false)
    } catch (error) {
      setFormError(getErrorMessage(error))
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{classifier ? "Edit Classifier" : "New Classifier"}</DialogTitle>
          <DialogDescription>
            Set the categories once, then let agents classify batches without restating the rules.
          </DialogDescription>
        </DialogHeader>

        <form
          className="flex flex-col gap-5"
          id="classifier-form"
          noValidate
          onSubmit={(event) => {
            void handleSubmit(event)
          }}
        >
          <FormAlerts
            error={formError}
            errorTitle="Classifier not saved"
            validationEntries={visibleValidationEntries}
          />

          <FieldGroup>
            <Field data-invalid={fieldErrors["classifier-display-name"] ? true : undefined}>
              <FieldLabel htmlFor="classifier-display-name">Name</FieldLabel>
              <Input
                aria-invalid={fieldErrors["classifier-display-name"] ? true : undefined}
                id="classifier-display-name"
                maxLength={100}
                onChange={(event) => {
                  setDisplayName(event.currentTarget.value)
                }}
                placeholder="Complaint triage"
                value={state.displayName}
              />
              <FieldDescription>
                Use a name your team will recognize in agent settings.
              </FieldDescription>
              <FieldError>{fieldErrors["classifier-display-name"]}</FieldError>
            </Field>

            <Field data-invalid={fieldErrors["classifier-description"] ? true : undefined}>
              <FieldLabel htmlFor="classifier-description">What should this classify?</FieldLabel>
              <Textarea
                aria-invalid={fieldErrors["classifier-description"] ? true : undefined}
                id="classifier-description"
                maxLength={1_024}
                onChange={(event) => {
                  setField("description", event.currentTarget.value)
                }}
                placeholder="Route customer messages by their primary intent."
                rows={3}
                value={state.description}
              />
              <FieldDescription>
                Agents see this purpose when choosing whether to use the classifier.
              </FieldDescription>
              <FieldError>{fieldErrors["classifier-description"]}</FieldError>
            </Field>

            <Field data-invalid={fieldErrors["classifier-instructions"] ? true : undefined}>
              <FieldLabel htmlFor="classifier-instructions">How should items be judged?</FieldLabel>
              <Textarea
                aria-invalid={fieldErrors["classifier-instructions"] ? true : undefined}
                id="classifier-instructions"
                maxLength={4_000}
                onChange={(event) => {
                  setField("instructions", event.currentTarget.value)
                }}
                placeholder="Choose the category that best matches the customer's main request."
                rows={4}
                value={state.instructions}
              />
              <FieldDescription>
                Optional guidance applies to every batch. Category guidance below handles the fine
                distinctions.
              </FieldDescription>
              <FieldError>{fieldErrors["classifier-instructions"]}</FieldError>
            </Field>
          </FieldGroup>

          <ClassifierLabelsEditor
            fieldErrors={fieldErrors}
            labels={state.labels}
            onAdd={addLabel}
            onRemove={removeLabel}
            onUpdate={updateLabel}
          />

          <details
            className="group rounded-md border"
            onToggle={(event) => {
              setAdvancedOpen(event.currentTarget.open)
            }}
            open={advancedOpen}
          >
            <summary className="focus-visible:ring-ring flex cursor-pointer list-none items-center justify-between gap-3 rounded-md px-4 py-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-offset-2 [&::-webkit-details-marker]:hidden">
              <span>
                <span className="font-medium">Advanced</span>
                <span className="text-muted-foreground ml-2">Tool name and helper model</span>
              </span>
              <ChevronDownIcon
                aria-hidden="true"
                className="text-muted-foreground size-4 transition-transform group-open:rotate-180"
              />
            </summary>
            <div className="grid gap-5 border-t p-4 sm:grid-cols-2">
              <Field data-invalid={fieldErrors["classifier-name"] ? true : undefined}>
                <FieldLabel htmlFor="classifier-name">Agent tool name</FieldLabel>
                <Input
                  aria-invalid={fieldErrors["classifier-name"] ? true : undefined}
                  id="classifier-name"
                  maxLength={48}
                  onChange={(event) => {
                    setField("name", event.currentTarget.value)
                  }}
                  placeholder="complaint_triage"
                  value={state.name}
                />
                <FieldDescription>
                  Agents call this as <code>classifier_{state.name || "name"}</code>.
                </FieldDescription>
                <FieldError>{fieldErrors["classifier-name"]}</FieldError>
              </Field>

              <Field data-invalid={fieldErrors["classifier-model"] ? true : undefined}>
                <FieldLabel htmlFor="classifier-model">Helper model</FieldLabel>
                <Select
                  onValueChange={(value) => {
                    setField("modelSelection", value ?? AUTOMATIC_CLASSIFIER_MODEL)
                  }}
                  value={state.modelSelection}
                >
                  <SelectTrigger
                    aria-invalid={fieldErrors["classifier-model"] ? true : undefined}
                    className="w-full"
                    id="classifier-model"
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent align="start">
                    <SelectGroup>
                      <SelectLabel>Classification models</SelectLabel>
                      {modelOptions.map((option) => (
                        <SelectItem key={option.value} label={option.label} value={option.value}>
                          {option.label}
                        </SelectItem>
                      ))}
                    </SelectGroup>
                  </SelectContent>
                </Select>
                <FieldDescription>
                  Automatic uses a configured low-cost model suited to structured results.
                </FieldDescription>
                <FieldError>{fieldErrors["classifier-model"]}</FieldError>
              </Field>
            </div>
          </details>

          <Field orientation="horizontal">
            <div className="flex flex-1 flex-col gap-0.5">
              <FieldLabel htmlFor="classifier-active">Available to agents</FieldLabel>
              <FieldDescription>
                Turn this off to remove the tool from new agent runs without deleting its setup.
              </FieldDescription>
            </div>
            <Switch
              aria-label="Available to agents"
              checked={state.isActive}
              id="classifier-active"
              onCheckedChange={(checked) => {
                setField("isActive", checked)
              }}
            />
          </Field>
        </form>

        <DialogFooter>
          <Button
            disabled={isPending}
            onClick={() => {
              onOpenChange(false)
            }}
            type="button"
            variant="outline"
          >
            Cancel
          </Button>
          <Button disabled={isPending} form="classifier-form" type="submit">
            {isPending ? "Saving" : classifier ? "Save Changes" : "Create Classifier"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function ClassifierLabelsEditor({
  fieldErrors,
  labels,
  onAdd,
  onRemove,
  onUpdate,
}: {
  fieldErrors: Record<string, string>
  labels: ClassifierLabelDraft[]
  onAdd: () => void
  onRemove: (key: number) => void
  onUpdate: (key: number, field: "description" | "label", value: string) => void
}) {
  return (
    <FieldSet id="classifier-labels">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <FieldLegend>What are the categories?</FieldLegend>
          <FieldDescription>
            Add at least two. Short guidance helps the model choose between similar categories.
          </FieldDescription>
        </div>
        <Button
          disabled={labels.length >= MAX_CLASSIFIER_LABELS}
          onClick={onAdd}
          size="sm"
          type="button"
          variant="outline"
        >
          <PlusIcon data-icon="inline-start" />
          Add Category
        </Button>
      </div>
      {fieldErrors["classifier-labels"] ? (
        <FieldError>{fieldErrors["classifier-labels"]}</FieldError>
      ) : null}

      <div className="flex flex-col gap-3">
        {labels.map((label, index) => {
          const labelFieldId = classifierLabelFieldId(label.key)
          const descriptionFieldId = classifierLabelDescriptionFieldId(label.key)
          const position = index + 1
          return (
            <div className="bg-muted/20 grid gap-3 rounded-lg border p-3" key={label.key}>
              <div className="flex items-center justify-between gap-3">
                <span className="text-muted-foreground text-xs font-medium tracking-wide uppercase">
                  Category {String(position)}
                </span>
                <Button
                  aria-label={`Remove category ${String(position)}`}
                  disabled={labels.length <= 2}
                  onClick={() => {
                    onRemove(label.key)
                  }}
                  size="icon-xs"
                  type="button"
                  variant="ghost"
                >
                  <Trash2Icon />
                </Button>
              </div>
              <div className="grid gap-3 sm:grid-cols-[minmax(0,0.75fr)_minmax(0,1.25fr)]">
                <Field data-invalid={fieldErrors[labelFieldId] ? true : undefined}>
                  <FieldLabel htmlFor={labelFieldId}>Category name</FieldLabel>
                  <Input
                    aria-invalid={fieldErrors[labelFieldId] ? true : undefined}
                    id={labelFieldId}
                    maxLength={64}
                    onChange={(event) => {
                      onUpdate(label.key, "label", event.currentTarget.value)
                    }}
                    placeholder={position === 1 ? "Complaint" : "Other"}
                    value={label.label}
                  />
                  <FieldError>{fieldErrors[labelFieldId]}</FieldError>
                </Field>
                <Field data-invalid={fieldErrors[descriptionFieldId] ? true : undefined}>
                  <FieldLabel htmlFor={descriptionFieldId}>When should this apply?</FieldLabel>
                  <Input
                    aria-invalid={fieldErrors[descriptionFieldId] ? true : undefined}
                    id={descriptionFieldId}
                    maxLength={256}
                    onChange={(event) => {
                      onUpdate(label.key, "description", event.currentTarget.value)
                    }}
                    placeholder={
                      position === 1 ? "The customer needs service recovery." : "Nothing else fits."
                    }
                    value={label.description}
                  />
                  <FieldError>{fieldErrors[descriptionFieldId]}</FieldError>
                </Field>
              </div>
            </div>
          )
        })}
      </div>
    </FieldSet>
  )
}
