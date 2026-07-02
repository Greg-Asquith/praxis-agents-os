// apps/web/src/features/agents/components/agent-form-model.ts

import { modelDisplayName } from "@/features/agents/components/agent-model-label"
import {
  RUNTIME_TOOL_OPTIONS,
  type RuntimeToolMode,
  type RuntimeToolName,
} from "@/features/agents/runtime-tools"
import type {
  Agent,
  AgentCreateRequest,
  AgentUpdateRequest,
  ToolPolicyValue,
} from "@/features/agents/types"
import type { ModelCatalogResponse } from "@/features/models/types"

const DEFAULT_MODEL_SELECTION = "Default"
export const NO_AGENT_SELECTION = "None"
const THINKING_DEFAULT = "Default"

export const THINKING_OPTIONS = [
  {
    value: THINKING_DEFAULT,
    label: "Model default",
    description: "Do not override the selected model's thinking behavior.",
  },
  {
    value: "true",
    label: "On",
    description: "Enable thinking with the provider default effort.",
  },
  {
    value: "false",
    label: "Off",
    description: "Disable thinking where the provider allows it.",
  },
  {
    value: "minimal",
    label: "Minimal",
    description: "Use the smallest supported thinking effort.",
  },
  {
    value: "low",
    label: "Low",
    description: "Use low thinking effort.",
  },
  {
    value: "medium",
    label: "Medium",
    description: "Use medium thinking effort.",
  },
  {
    value: "high",
    label: "High",
    description: "Use high thinking effort.",
  },
  {
    value: "xhigh",
    label: "Extra high",
    description: "Use the highest supported thinking effort.",
  },
] as const

type ThinkingSelection = (typeof THINKING_OPTIONS)[number]["value"]

export type AgentFormState = {
  allowedAgentIds: string[]
  azureDeployment: string
  description: string
  instructions: string
  isActive: "true" | "false"
  isFavorite: "true" | "false"
  maxSteps: string
  modelSelection: string
  modelSettings: Record<string, unknown>
  name: string
  slug: string
  thinking: ThinkingSelection
  toolModes: Record<RuntimeToolName, RuntimeToolMode>
}

export type AgentFormValidationEntry = {
  fieldId: string
  label: string
  message: string
}

export type AgentFormFieldSetter = <K extends keyof AgentFormState>(
  field: K,
  value: AgentFormState[K]
) => void

export type ModelOption = {
  description: string
  label: string
  supportsThinking: boolean | null
  value: string
}

type ModelSelection = {
  azure_deployment: string | null
  model: string | null
  model_provider: string | null
}

export function initialAgentFormState(agent: Agent | null): AgentFormState {
  return {
    allowedAgentIds: agent?.allowed_agent_ids ?? [],
    azureDeployment: agent?.azure_deployment ?? "",
    description: agent?.description ?? "",
    instructions: agent?.instructions ?? "",
    isActive: agent?.is_active === false ? "false" : "true",
    isFavorite: agent?.is_favorite ? "true" : "false",
    maxSteps: String(agent?.max_steps ?? 20),
    modelSelection: modelSelectionFromAgent(agent),
    modelSettings: { ...(agent?.model_settings ?? {}) },
    name: agent?.name ?? "",
    slug: agent?.slug ?? "",
    thinking: thinkingSelectionFromSettings(agent?.model_settings ?? null),
    toolModes: initialToolModes(agent),
  }
}

export function buildModelOptions(
  catalog: ModelCatalogResponse,
  agent: Agent | null
): ModelOption[] {
  const options: ModelOption[] = [
    {
      value: DEFAULT_MODEL_SELECTION,
      label: catalog.defaults.agent_model
        ? `Workspace default (${modelDisplayName(catalog, catalog.defaults.agent_model) ?? catalog.defaults.agent_model})`
        : "Workspace default",
      description: "Use the backend default configured for agent runs.",
      supportsThinking: null,
    },
    ...catalog.models.map((model) => ({
      value: model.id,
      label: modelDisplayName(catalog, model.id) ?? model.id,
      description: `${model.context_window.toLocaleString()} token context${
        model.supports_tools ? " · tools" : ""
      }${model.supports_thinking ? " · thinking" : ""}`,
      supportsThinking: model.supports_thinking,
    })),
  ]

  const currentSelection = modelSelectionFromAgent(agent)
  if (
    currentSelection !== DEFAULT_MODEL_SELECTION &&
    !options.some((option) => option.value === currentSelection)
  ) {
    options.splice(1, 0, {
      value: currentSelection,
      label: `Current override (${currentSelection})`,
      description: "This saved model is not present in the configured catalog response.",
      supportsThinking: null,
    })
  }

  return options
}

export function buildAgentPayload(
  state: AgentFormState,
  mode: "create"
): AgentCreateRequest | string
export function buildAgentPayload(state: AgentFormState, mode: "edit"): AgentUpdateRequest | string
export function buildAgentPayload(
  state: AgentFormState,
  mode: "create" | "edit"
): AgentCreateRequest | AgentUpdateRequest | string {
  const name = state.name.trim()
  const instructions = state.instructions.trim()
  const validationEntries = validateAgentFormState(state, mode)
  const maxSteps = parseMaxSteps(state.maxSteps)
  const modelSelection = parseModelSelection(state.modelSelection, state.azureDeployment)

  const firstValidationEntry = validationEntries[0]
  if (firstValidationEntry) {
    return firstValidationEntry.message
  }
  if (typeof maxSteps === "string") {
    return maxSteps
  }
  if (typeof modelSelection === "string") {
    return modelSelection
  }

  const toolPayload = buildToolPayload(state.toolModes)
  const modelSettings = buildModelSettings(state)
  const basePayload = {
    allowed_agent_ids: state.allowedAgentIds,
    azure_deployment: modelSelection.azure_deployment,
    description: optionalText(state.description),
    instructions,
    is_active: state.isActive === "true",
    is_favorite: state.isFavorite === "true",
    max_steps: maxSteps,
    model: modelSelection.model,
    model_provider: modelSelection.model_provider,
    model_settings: modelSettings,
    name,
    tool_names: toolPayload.tool_names,
    tool_policies: toolPayload.tool_policies,
  }

  if (mode === "create") {
    return {
      ...basePayload,
      skill_ids: [],
      slug: optionalText(state.slug),
    }
  }

  const slug = state.slug.trim()
  if (!slug) {
    return "Slug is required for existing agents."
  }

  return {
    ...basePayload,
    slug,
  }
}

export function validateAgentFormState(
  state: AgentFormState,
  mode: "create" | "edit"
): AgentFormValidationEntry[] {
  const entries: AgentFormValidationEntry[] = []

  if (!state.name.trim()) {
    entries.push({
      fieldId: "agent-name",
      label: "Name",
      message: "Name is required.",
    })
  }

  if (mode === "edit" && !state.slug.trim()) {
    entries.push({
      fieldId: "agent-slug",
      label: "Slug",
      message: "Slug is required for existing agents.",
    })
  }

  if (!state.instructions.trim()) {
    entries.push({
      fieldId: "agent-instructions",
      label: "Instructions",
      message: "Instructions are required.",
    })
  }

  const maxSteps = parseMaxSteps(state.maxSteps)
  if (typeof maxSteps === "string") {
    entries.push({
      fieldId: "agent-max-steps",
      label: "Max steps",
      message: maxSteps,
    })
  }

  const modelSelection = parseModelSelection(state.modelSelection, state.azureDeployment)
  if (typeof modelSelection === "string") {
    entries.push({
      fieldId: "agent-model",
      label: "Model",
      message: modelSelection,
    })
  }

  return entries
}

export function isAgentFormDirty(current: AgentFormState, initial: AgentFormState) {
  return (
    current.name !== initial.name ||
    current.slug !== initial.slug ||
    current.description !== initial.description ||
    current.instructions !== initial.instructions ||
    current.modelSelection !== initial.modelSelection ||
    current.azureDeployment !== initial.azureDeployment ||
    current.maxSteps !== initial.maxSteps ||
    current.isActive !== initial.isActive ||
    current.isFavorite !== initial.isFavorite ||
    current.thinking !== initial.thinking ||
    !stringArraysEqual(current.allowedAgentIds, initial.allowedAgentIds) ||
    !toolModesEqual(current.toolModes, initial.toolModes) ||
    JSON.stringify(current.modelSettings) !== JSON.stringify(initial.modelSettings)
  )
}

function initialToolModes(agent: Agent | null): Record<RuntimeToolName, RuntimeToolMode> {
  const toolNames = new Set(agent?.tool_names ?? [])
  const policies = agent?.tool_policies ?? {}
  return RUNTIME_TOOL_OPTIONS.reduce<Record<RuntimeToolName, RuntimeToolMode>>(
    (toolModes, tool) => {
      const savedPolicy = policies[tool.name]
      toolModes[tool.name] = toolNames.has(tool.name) ? (savedPolicy ?? "auto") : "off"
      return toolModes
    },
    {
      add_numbers: "off",
      get_runtime_context: "off",
    }
  )
}

function stringArraysEqual(left: string[], right: string[]) {
  if (left.length !== right.length) {
    return false
  }

  return left.every((value, index) => value === right[index])
}

function toolModesEqual(
  left: Record<RuntimeToolName, RuntimeToolMode>,
  right: Record<RuntimeToolName, RuntimeToolMode>
) {
  return RUNTIME_TOOL_OPTIONS.every((tool) => left[tool.name] === right[tool.name])
}

function modelSelectionFromAgent(agent: Agent | null) {
  if (!agent?.model_provider || !agent.model) {
    return DEFAULT_MODEL_SELECTION
  }

  return `${agent.model_provider}:${agent.model}`
}

function thinkingSelectionFromSettings(
  modelSettings: Record<string, unknown> | null
): ThinkingSelection {
  const value = modelSettings?.["thinking"]
  if (value === true) {
    return "true"
  }
  if (value === false) {
    return "false"
  }
  if (typeof value === "string" && isThinkingSelection(value)) {
    return value
  }

  return THINKING_DEFAULT
}

function isThinkingSelection(value: string): value is ThinkingSelection {
  return THINKING_OPTIONS.some((option) => option.value === value)
}

function buildToolPayload(toolModes: AgentFormState["toolModes"]) {
  const toolNames: string[] = []
  const toolPolicies: Record<string, ToolPolicyValue> = {}

  for (const tool of RUNTIME_TOOL_OPTIONS) {
    const mode = toolModes[tool.name]
    if (mode === "off") {
      continue
    }

    toolNames.push(tool.name)
    toolPolicies[tool.name] = mode
  }

  return {
    tool_names: toolNames,
    tool_policies: Object.keys(toolPolicies).length > 0 ? toolPolicies : null,
  }
}

function buildModelSettings(state: AgentFormState) {
  const modelSettings = { ...state.modelSettings }

  if (state.thinking === THINKING_DEFAULT) {
    delete modelSettings["thinking"]
  } else if (state.thinking === "true") {
    modelSettings["thinking"] = true
  } else if (state.thinking === "false") {
    modelSettings["thinking"] = false
  } else {
    modelSettings["thinking"] = state.thinking
  }

  return Object.keys(modelSettings).length > 0 ? modelSettings : null
}

function parseMaxSteps(rawValue: string): number | null | string {
  const value = rawValue.trim()
  if (!value) {
    return null
  }

  const parsed = Number(value)
  if (!Number.isInteger(parsed) || parsed < 1 || parsed > 100) {
    return "Max steps must be a whole number from 1 to 100."
  }

  return parsed
}

function parseModelSelection(value: string, azureDeployment: string): ModelSelection | string {
  if (value === DEFAULT_MODEL_SELECTION) {
    return { azure_deployment: null, model: null, model_provider: null }
  }

  const separatorIndex = value.indexOf(":")
  if (separatorIndex <= 0 || separatorIndex === value.length - 1) {
    return "Model selection is invalid."
  }

  const provider = value.slice(0, separatorIndex)
  const model = value.slice(separatorIndex + 1)
  return {
    azure_deployment: provider === "azure" ? optionalText(azureDeployment) : null,
    model,
    model_provider: provider,
  }
}

function optionalText(value: string) {
  const normalized = value.trim()
  return normalized ? normalized : null
}
