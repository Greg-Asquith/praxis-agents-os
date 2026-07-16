// apps/web/src/features/skills/components/skill-form.tsx

import { useId, useMemo, useRef, useState, type ReactNode, type SyntheticEvent } from "react"

import { FormAlerts } from "@/components/forms/form-alerts"
import { FormWizard, type FormWizardNavigation } from "@/components/forms/form-wizard"
import {
  buildSkillPayload,
  initialSkillFormState,
  isSkillFormDirty,
  validateSkillFormState,
  type SkillFormState,
} from "@/features/skills/components/skill-form-model"
import {
  EMPTY_PENDING_SKILL_DOCUMENT_DRAFT,
  type PendingSkillDocumentDraft,
  type PendingSkillDocumentUpload,
} from "@/features/skills/components/pending-skill-document-model"
import { PendingSkillDocumentsSection } from "@/features/skills/components/pending-skill-documents-section"
import { SkillAvailabilitySection } from "@/features/skills/components/skill-availability-section"
import { SkillIdentitySection } from "@/features/skills/components/skill-identity-section"
import { SkillInstructionsSection } from "@/features/skills/components/skill-instructions-section"
import {
  SKILL_CREATE_STEPS,
  SKILL_EDIT_STEPS,
  skillValidationEntriesForStep,
  stepForSkillField,
  type SkillWizardStepId,
} from "@/features/skills/components/skill-form-wizard-config"
import type { Skill, SkillCreateRequest, SkillUpdateRequest } from "@/features/skills/types"
import { getErrorMessage } from "@/lib/api/errors"
import { buildFieldErrors } from "@/lib/forms"

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
      onSubmit: (payload: SkillUpdateRequest) => Promise<void>
      skill: Skill
    }

export function SkillForm(props: SkillFormProps) {
  const formId = useId()
  const wizardNavigationRef = useRef<FormWizardNavigation<SkillWizardStepId>>(null)
  const skill = props.mode === "edit" ? props.skill : null
  const initialState = useMemo(() => initialSkillFormState(skill), [skill])
  const [state, setState] = useState<SkillFormState>(() => initialState)
  const [formError, setFormError] = useState<string | null>(null)
  const [validationStep, setValidationStep] = useState<SkillWizardStepId | null>(null)
  const [pendingDocuments, setPendingDocuments] = useState<PendingSkillDocumentUpload[]>([])
  const [pendingDocumentDraft, setPendingDocumentDraft] = useState<PendingSkillDocumentDraft>(
    EMPTY_PENDING_SKILL_DOCUMENT_DRAFT
  )
  const fullValidationEntries = useMemo(() => validateSkillFormState(state), [state])
  const isDirty = props.mode === "edit" ? isSkillFormDirty(state, initialState) : true

  function setField<K extends keyof SkillFormState>(field: K, value: SkillFormState[K]) {
    setState((current) => ({ ...current, [field]: value }))
  }

  async function handleSubmit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault()
    setFormError(null)

    const nextValidationEntries = validateSkillFormState(state)
    if (nextValidationEntries.length > 0) {
      const earliestStep = stepForSkillField(nextValidationEntries[0]?.fieldId)
      setValidationStep(earliestStep)
      wizardNavigationRef.current?.goToStep(earliestStep)
      return
    }

    setValidationStep(null)

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

  function validateStep(stepId: SkillWizardStepId) {
    const stepValidationEntries = skillValidationEntriesForStep(fullValidationEntries, stepId)
    setValidationStep(stepId)
    return stepValidationEntries.length === 0
  }

  const wizard = (
    <FormWizard
      cancelLabel={props.cancelLabel}
      cancelTo="/skills"
      disableSubmit={props.mode === "edit" && !isDirty}
      {...(props.mode === "edit" ? { form: formId } : {})}
      isSubmitting={props.isSubmitting}
      navigationRef={wizardNavigationRef}
      pendingLabel={props.mode === "create" ? "Creating" : "Saving"}
      steps={props.mode === "create" ? SKILL_CREATE_STEPS : SKILL_EDIT_STEPS}
      submitLabel={props.mode === "create" ? "Create Skill" : "Save Changes"}
      validateStep={validateStep}
    >
      {(activeStepId) => {
        const validationEntries =
          validationStep === activeStepId
            ? skillValidationEntriesForStep(fullValidationEntries, activeStepId)
            : []
        const fieldErrors = buildFieldErrors(validationEntries)

        return (
          <div className="flex flex-col gap-6">
            <FormAlerts
              error={formError}
              errorTitle="Skill not saved"
              validationEntries={validationEntries}
            />
            {activeStepId === "identity" ? (
              <SkillIdentitySection
                description={state.description}
                fieldErrors={fieldErrors}
                mode={props.mode}
                name={state.name}
                onDescriptionChange={(description) => {
                  setField("description", description)
                }}
                onNameChange={(name) => {
                  setField("name", name)
                }}
              />
            ) : null}
            {activeStepId === "instructions" ? (
              <SkillInstructionsSection
                fieldErrors={fieldErrors}
                instructions={state.instructions}
                mode={props.mode}
                onInstructionsChange={(instructions) => {
                  setField("instructions", instructions)
                }}
              />
            ) : null}
            {activeStepId === "documents" ? (
              props.mode === "create" ? (
                <PendingSkillDocumentsSection
                  documents={pendingDocuments}
                  draft={pendingDocumentDraft}
                  onDocumentsChange={setPendingDocuments}
                  onDraftChange={setPendingDocumentDraft}
                />
              ) : (
                props.children
              )
            ) : null}
            {activeStepId === "availability" && props.mode === "edit" ? (
              <SkillAvailabilitySection
                isActive={state.isActive}
                isFavorite={state.isFavorite}
                onActiveChange={(isActive) => {
                  setField("isActive", isActive)
                }}
                onFavoriteChange={(isFavorite) => {
                  setField("isFavorite", isFavorite)
                }}
              />
            ) : null}
          </div>
        )
      }}
    </FormWizard>
  )

  if (props.mode === "create") {
    return (
      <form
        id={formId}
        noValidate
        onSubmit={(event) => {
          void handleSubmit(event)
        }}
      >
        {wizard}
      </form>
    )
  }

  return (
    <div className="flex flex-col gap-6">
      <form
        id={formId}
        noValidate
        onSubmit={(event) => {
          void handleSubmit(event)
        }}
      />
      {wizard}
    </div>
  )
}
