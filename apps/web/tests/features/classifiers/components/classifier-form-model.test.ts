import { describe, expect, it } from "vitest"

import {
  AUTOMATIC_CLASSIFIER_MODEL,
  buildClassifierModelOptions,
  buildClassifierPayload,
  classifierIdentifierFromName,
  initialClassifierFormState,
  validateClassifierFormState,
  type ClassifierFormState,
} from "@/features/classifiers/components/classifier-form-model"
import type { Classifier } from "@/features/classifiers/types"
import type { ModelCatalogResponse } from "@/features/models/types"

const classifier: Classifier = {
  created_at: "2026-08-18T09:00:00Z",
  created_by: "user-1",
  description: "Route customer messages by primary intent.",
  display_name: "Complaint triage",
  id: "classifier-1",
  instructions: "Prefer complaint when recovery is needed.",
  is_active: false,
  labels: [
    { description: "Needs service recovery.", label: "Complaint" },
    { description: null, label: "Other" },
  ],
  model: "gpt-5.6-luna",
  model_provider: "openai",
  name: "complaint_triage",
  updated_at: "2026-08-18T10:00:00Z",
  workspace_id: "workspace-1",
}

const modelCatalog: ModelCatalogResponse = {
  defaults: { agent_model: "openai:gpt-5.4-mini" },
  models: [
    {
      context_window: 100_000,
      default_settings: {},
      display_name: "GPT 5.6 Luna",
      id: "openai:gpt-5.6-luna",
      model: "gpt-5.6-luna",
      provider: "openai",
      supports_structured_output: true,
      supports_thinking: false,
      supports_tools: true,
      supports_vision: false,
    },
    {
      context_window: 100_000,
      default_settings: {},
      display_name: "Unstructured",
      id: "openai:unstructured",
      model: "unstructured",
      provider: "openai",
      supports_structured_output: false,
      supports_thinking: false,
      supports_tools: true,
      supports_vision: false,
    },
    {
      context_window: 100_000,
      default_settings: {},
      display_name: "Unavailable",
      id: "anthropic:unavailable",
      model: "unavailable",
      provider: "anthropic",
      supports_structured_output: true,
      supports_thinking: false,
      supports_tools: true,
      supports_vision: false,
    },
  ],
  providers: [
    { configured: true, display_name: "OpenAI", model_count: 2, provider: "openai" },
    { configured: false, display_name: "Anthropic", model_count: 1, provider: "anthropic" },
  ],
}

describe("classifier form model", () => {
  it("round-trips every persisted field through the edit payload", () => {
    const state = initialClassifierFormState(classifier)

    expect(buildClassifierPayload(state)).toEqual({
      description: classifier.description,
      display_name: classifier.display_name,
      instructions: classifier.instructions,
      is_active: false,
      labels: classifier.labels,
      model: classifier.model,
      model_provider: classifier.model_provider,
      name: classifier.name,
    })
  })

  it("normalizes a create payload and supports the automatic model", () => {
    const state: ClassifierFormState = {
      description: "  Sort feedback.  ",
      displayName: " Feedback triage ",
      instructions: "   ",
      isActive: true,
      labels: [
        { description: "  Happy customer. ", key: 0, label: " Praise  " },
        { description: "", key: 1, label: "Needs   help" },
      ],
      modelSelection: AUTOMATIC_CLASSIFIER_MODEL,
      name: "feedback_triage",
    }

    expect(buildClassifierPayload(state)).toEqual({
      description: "Sort feedback.",
      display_name: "Feedback triage",
      instructions: null,
      is_active: true,
      labels: [
        { description: "Happy customer.", label: "Praise" },
        { description: null, label: "Needs help" },
      ],
      model: null,
      model_provider: null,
      name: "feedback_triage",
    })
    expect(classifierIdentifierFromName("  Réfund / Follow-up  ")).toBe("refund_follow_up")
  })

  it("reports label count, duplicate, blank, and length errors locally", () => {
    const state = initialClassifierFormState(null)
    state.displayName = "Triage"
    state.description = "Sort messages."
    state.name = "triage"
    state.labels = [
      { description: "x".repeat(257), key: 0, label: " Same " },
      { description: "", key: 1, label: "Same" },
      { description: "", key: 2, label: "" },
    ]

    expect(validateClassifierFormState(state).map((entry) => entry.message)).toEqual([
      "Category guidance must be 256 characters or fewer.",
      "Category names must be unique.",
      "Category name is required.",
    ])

    state.labels = state.labels.slice(0, 1)
    expect(validateClassifierFormState(state).map((entry) => entry.message)).toContain(
      "Add at least two categories."
    )
  })

  it("offers automatic plus configured structured-output models only", () => {
    expect(buildClassifierModelOptions(modelCatalog, null)).toEqual([
      { label: "Automatic (recommended)", value: "automatic" },
      { label: "OpenAI · GPT 5.6 Luna", value: "openai:gpt-5.6-luna" },
    ])
  })
})
