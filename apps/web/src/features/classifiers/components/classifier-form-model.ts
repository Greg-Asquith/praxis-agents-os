// apps/web/src/features/classifiers/components/classifier-form-model.ts

import type { Classifier, ClassifierCreateRequest } from "@/features/classifiers/types"
import type { ModelCatalogResponse } from "@/features/models/types"
import type { FormValidationEntry } from "@/lib/forms"

export const AUTOMATIC_CLASSIFIER_MODEL = "automatic"
export const MAX_CLASSIFIER_LABELS = 50

const CLASSIFIER_NAME_PATTERN = /^[a-z][a-z0-9_]*$/
const SUPPORTED_CLASSIFIER_PROVIDERS = new Set(["anthropic", "google", "openai"])

export type ClassifierLabelDraft = {
  description: string
  key: number
  label: string
}

export type ClassifierFormState = {
  description: string
  displayName: string
  instructions: string
  isActive: boolean
  labels: ClassifierLabelDraft[]
  modelSelection: string
  name: string
}

export type ClassifierModelOption = {
  label: string
  value: string
}

export function classifierIdentifierFromName(value: string) {
  return value
    .trim()
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .replace(/_+/g, "_")
}

export function initialClassifierFormState(classifier: Classifier | null): ClassifierFormState {
  return {
    description: classifier?.description ?? "",
    displayName: classifier?.display_name ?? "",
    instructions: classifier?.instructions ?? "",
    isActive: classifier?.is_active ?? true,
    labels:
      classifier?.labels.map((label, index) => ({
        description: label.description ?? "",
        key: index,
        label: label.label,
      })) ?? emptyClassifierLabels(),
    modelSelection:
      classifier?.model_provider && classifier.model
        ? `${classifier.model_provider}:${classifier.model}`
        : AUTOMATIC_CLASSIFIER_MODEL,
    name: classifier?.name ?? "",
  }
}

export function buildClassifierModelOptions(
  catalog: ModelCatalogResponse,
  classifier: Classifier | null
): ClassifierModelOption[] {
  const configuredProviders = new Set(
    catalog.providers.filter((provider) => provider.configured).map((provider) => provider.provider)
  )
  const options: ClassifierModelOption[] = [
    { label: "Automatic (recommended)", value: AUTOMATIC_CLASSIFIER_MODEL },
    ...catalog.models
      .filter(
        (model) =>
          model.supports_structured_output &&
          SUPPORTED_CLASSIFIER_PROVIDERS.has(model.provider) &&
          configuredProviders.has(model.provider)
      )
      .map((model) => ({
        label: `${providerDisplayName(catalog, model.provider)} · ${model.display_name}`,
        value: model.id,
      })),
  ]
  const currentSelection = initialClassifierFormState(classifier).modelSelection
  if (
    currentSelection !== AUTOMATIC_CLASSIFIER_MODEL &&
    !options.some((option) => option.value === currentSelection)
  ) {
    options.splice(1, 0, {
      label: `Current override (${currentSelection})`,
      value: currentSelection,
    })
  }
  return options
}

export function buildClassifierPayload(
  state: ClassifierFormState
): ClassifierCreateRequest | string {
  const firstValidationEntry = validateClassifierFormState(state)[0]
  if (firstValidationEntry) {
    return firstValidationEntry.message
  }

  const model = parseModelSelection(state.modelSelection)
  if (typeof model === "string") {
    return model
  }

  return {
    description: state.description.trim(),
    display_name: state.displayName.trim(),
    instructions: optionalText(state.instructions),
    is_active: state.isActive,
    labels: state.labels.map((label) => ({
      description: optionalText(label.description),
      label: normalizeLabel(label.label),
    })),
    model: model.model,
    model_provider: model.model_provider,
    name: state.name.trim(),
  }
}

export function validateClassifierFormState(state: ClassifierFormState): FormValidationEntry[] {
  const entries: FormValidationEntry[] = []
  const displayName = state.displayName.trim()
  const name = state.name.trim()
  const description = state.description.trim()
  const instructions = state.instructions.trim()

  if (!displayName) {
    entries.push(fieldError("classifier-display-name", "Name", "Name is required."))
  } else if (displayName.length > 100) {
    entries.push(
      fieldError("classifier-display-name", "Name", "Name must be 100 characters or fewer.")
    )
  }

  if (!description) {
    entries.push(
      fieldError("classifier-description", "Purpose", "Describe what this classifier decides.")
    )
  } else if (description.length > 1_024) {
    entries.push(
      fieldError("classifier-description", "Purpose", "Purpose must be 1,024 characters or fewer.")
    )
  }

  if (instructions.length > 4_000) {
    entries.push(
      fieldError(
        "classifier-instructions",
        "Judging guidance",
        "Judging guidance must be 4,000 characters or fewer."
      )
    )
  }

  if (state.labels.length < 2) {
    entries.push(fieldError("classifier-labels", "Categories", "Add at least two categories."))
  } else if (state.labels.length > MAX_CLASSIFIER_LABELS) {
    entries.push(
      fieldError(
        "classifier-labels",
        "Categories",
        `Use no more than ${String(MAX_CLASSIFIER_LABELS)} categories.`
      )
    )
  }

  const normalizedLabels = new Map<string, number>()
  for (const [index, label] of state.labels.entries()) {
    const normalizedLabel = normalizeLabel(label.label)
    const labelFieldId = classifierLabelFieldId(label.key)
    const descriptionFieldId = classifierLabelDescriptionFieldId(label.key)
    const position = index + 1
    if (!normalizedLabel) {
      entries.push(
        fieldError(labelFieldId, `Category ${String(position)}`, "Category name is required.")
      )
    } else if (normalizedLabel.length > 64) {
      entries.push(
        fieldError(
          labelFieldId,
          `Category ${String(position)}`,
          "Category name must be 64 characters or fewer."
        )
      )
    } else if (normalizedLabels.has(normalizedLabel)) {
      entries.push(
        fieldError(labelFieldId, `Category ${String(position)}`, "Category names must be unique.")
      )
    } else {
      normalizedLabels.set(normalizedLabel, index)
    }
    if (label.description.trim().length > 256) {
      entries.push(
        fieldError(
          descriptionFieldId,
          `Category ${String(position)} guidance`,
          "Category guidance must be 256 characters or fewer."
        )
      )
    }
  }

  if (!name) {
    entries.push(fieldError("classifier-name", "Agent tool name", "Agent tool name is required."))
  } else if (name.length > 48) {
    entries.push(
      fieldError(
        "classifier-name",
        "Agent tool name",
        "Agent tool name must be 48 characters or fewer."
      )
    )
  } else if (!CLASSIFIER_NAME_PATTERN.test(name)) {
    entries.push(
      fieldError(
        "classifier-name",
        "Agent tool name",
        "Use lowercase letters, numbers, and underscores, starting with a letter."
      )
    )
  }

  if (typeof parseModelSelection(state.modelSelection) === "string") {
    entries.push(fieldError("classifier-model", "Helper model", "Choose a valid helper model."))
  }

  return entries
}

export function classifierLabelFieldId(key: number) {
  return `classifier-label-${String(key)}`
}

export function classifierLabelDescriptionFieldId(key: number) {
  return `classifier-label-description-${String(key)}`
}

function emptyClassifierLabels(): ClassifierLabelDraft[] {
  return [
    { description: "", key: 0, label: "" },
    { description: "", key: 1, label: "" },
  ]
}

function providerDisplayName(catalog: ModelCatalogResponse, providerName: string) {
  return (
    catalog.providers.find((provider) => provider.provider === providerName)?.display_name ??
    providerName
  )
}

function parseModelSelection(
  selection: string
): { model: string | null; model_provider: string | null } | string {
  if (selection === AUTOMATIC_CLASSIFIER_MODEL) {
    return { model: null, model_provider: null }
  }
  const separator = selection.indexOf(":")
  if (separator < 1 || separator === selection.length - 1) {
    return "Choose a valid helper model."
  }
  const modelProvider = selection.slice(0, separator)
  if (!SUPPORTED_CLASSIFIER_PROVIDERS.has(modelProvider)) {
    return "Choose a valid helper model."
  }
  return {
    model: selection.slice(separator + 1),
    model_provider: modelProvider,
  }
}

function normalizeLabel(value: string) {
  return value.trim().replace(/\s+/g, " ")
}

function optionalText(value: string) {
  const normalized = value.trim()
  return normalized || null
}

function fieldError(fieldId: string, label: string, message: string): FormValidationEntry {
  return { fieldId, label, message }
}
