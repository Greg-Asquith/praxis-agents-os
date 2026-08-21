import { describe, expect, it } from "vitest"

import {
  buildAgentPayload,
  buildModelTypeOptions,
  buildModelOptions,
  buildProviderOptions,
  initialAgentFormState,
  isAgentFormDirty,
  modelSelectionForProvider,
  modelSelectionForType,
  simpleSelectionFromModel,
  validateAgentFormState,
  type AgentFormState,
} from "@/features/agents/components/agent-form-model"
import type { Agent } from "@/features/agents/types"
import type { ModelCatalogResponse, ModelType } from "@/features/models/types"
import type { ToolCatalogEntry } from "@/features/tools/types"

const toolCatalog: ToolCatalogEntry[] = [
  {
    name: "read_file",
    provider: "core",
    label: "Read file",
    description: "Read workspace files.",
    kind: "function",
    effect: "read",
    effect_scope: "internal",
    egress: "none",
    default_policy: "auto",
    supported_policies: ["auto", "approval"],
    defer_loading: false,
  },
  {
    name: "send_email",
    provider: "gmail",
    label: "Send email",
    description: "Send an email.",
    kind: "function",
    effect: "write",
    effect_scope: "external",
    egress: "external_write",
    default_policy: "approval",
    supported_policies: ["approval"],
    defer_loading: false,
  },
]

const agent: Agent = {
  id: "agent-1",
  name: "Planner",
  slug: "planner",
  description: "Plans work",
  instructions: "Plan the work carefully.",
  workspace_id: "workspace-1",
  created_by: "user-1",
  code_mode_enabled: true,
  tool_names: ["read_file", "missing_tool"],
  tool_policies: { read_file: "approval" },
  skill_ids: ["skill-1"],
  allowed_agent_ids: ["agent-2"],
  model_provider: "openai",
  model: "gpt-5.4-mini",
  model_settings: { temperature: 0.2, thinking: "high" },
  azure_deployment: null,
  max_steps: 12,
  is_active: false,
  is_favorite: true,
  last_used_at: null,
  metadata: null,
  created_at: "2026-07-07T10:00:00.000Z",
  updated_at: "2026-07-07T10:00:00.000Z",
  deleted: false,
  deleted_at: null,
}

function catalogModel({
  displayName,
  id,
  modelType,
}: {
  displayName: string
  id: string
  modelType: ModelType
}): ModelCatalogResponse["models"][number] {
  const [provider = "", model = ""] = id.split(":")
  return {
    context_window: 128_000,
    default_settings: {},
    display_name: displayName,
    id,
    model,
    model_type: modelType,
    provider,
    supports_structured_output: true,
    supports_thinking: true,
    supports_tools: true,
    supports_vision: true,
  }
}

const modelCatalog: ModelCatalogResponse = {
  defaults: { agent_model: "openai:gpt-5.6-luna" },
  models: [
    catalogModel({ displayName: "GPT-5.6 Luna", id: "openai:gpt-5.6-luna", modelType: "standard" }),
    catalogModel({ displayName: "GPT-5.4 Nano", id: "openai:gpt-5.4-nano", modelType: "light" }),
    catalogModel({
      displayName: "Claude Fable 5",
      id: "anthropic:claude-fable-5",
      modelType: "max",
    }),
    catalogModel({
      displayName: "Claude Opus 4.8",
      id: "anthropic:claude-opus-4-8",
      modelType: "powerful",
    }),
    catalogModel({
      displayName: "Claude Opus 4.7",
      id: "anthropic:claude-opus-4-7",
      modelType: "powerful",
    }),
    catalogModel({
      displayName: "Claude Sonnet 5",
      id: "anthropic:claude-sonnet-5",
      modelType: "standard",
    }),
    catalogModel({
      displayName: "Claude Haiku 4.5",
      id: "anthropic:claude-haiku-4-5",
      modelType: "light",
    }),
    catalogModel({
      displayName: "Gemini 3.7 Flash",
      id: "google:gemini-3.7-flash",
      modelType: "standard",
    }),
    catalogModel({
      displayName: "Gemini 3.5 Flash-Lite",
      id: "google:gemini-3.5-flash-lite",
      modelType: "light",
    }),
    catalogModel({
      displayName: "Gemini 3.1 Pro",
      id: "google:gemini-3.1-pro",
      modelType: "powerful",
    }),
  ],
  providers: [
    {
      configured: true,
      display_name: "OpenAI",
      model_count: 2,
      model_type_defaults: {
        light: "openai:gpt-5.4-nano",
        standard: "openai:gpt-5.6-luna",
      },
      provider: "openai",
    },
    {
      configured: true,
      display_name: "Anthropic",
      model_count: 4,
      model_type_defaults: {
        light: "anthropic:claude-haiku-4-5",
        max: "anthropic:claude-fable-5",
        powerful: "anthropic:claude-opus-4-8",
        standard: "anthropic:claude-sonnet-5",
      },
      provider: "anthropic",
    },
    {
      configured: true,
      display_name: "Google",
      model_count: 3,
      model_type_defaults: {
        light: "google:gemini-3.5-flash-lite",
        powerful: "google:gemini-3.1-pro",
        standard: "google:gemini-3.7-flash",
      },
      provider: "google",
    },
    {
      configured: true,
      display_name: "Azure OpenAI",
      model_count: 0,
      model_type_defaults: {},
      provider: "azure",
    },
    {
      configured: false,
      display_name: "Unavailable",
      model_count: 1,
      model_type_defaults: {},
      provider: "unavailable",
    },
  ],
}

function validState(overrides: Partial<AgentFormState> = {}): AgentFormState {
  return {
    allowedAgentIds: ["agent-2"],
    azureDeployment: "",
    codeModeEnabled: false,
    description: "  Helps plan launches.  ",
    identityColor: "Auto",
    instructions: "  Use the playbook.  ",
    isActive: "true",
    isFavorite: "false",
    maxSteps: "25",
    metadataJson: {},
    modelSelection: "openai:gpt-5.4-mini",
    modelSettings: { temperature: 0.1 },
    name: "  Launch planner  ",
    skillIds: ["skill-1"],
    thinking: "low",
    toolModes: {
      read_file: "auto",
      send_email: "approval",
    },
    ...overrides,
  }
}

describe("initialAgentFormState", () => {
  it("uses documented defaults for new agents", () => {
    const state = initialAgentFormState(null, toolCatalog)

    expect(state).toEqual({
      allowedAgentIds: [],
      azureDeployment: "",
      codeModeEnabled: false,
      description: "",
      identityColor: "Auto",
      instructions: "",
      isActive: "true",
      isFavorite: "false",
      maxSteps: "20",
      metadataJson: {},
      modelSelection: "Default",
      modelSettings: {},
      name: "",
      skillIds: [],
      thinking: "Default",
      toolModes: {
        read_file: "off",
        send_email: "off",
      },
    })
  })

  it("round-trips an existing agent into editable state", () => {
    const state = initialAgentFormState(agent, toolCatalog)

    expect(state).toEqual({
      allowedAgentIds: ["agent-2"],
      azureDeployment: "",
      codeModeEnabled: true,
      description: "Plans work",
      identityColor: "Auto",
      instructions: "Plan the work carefully.",
      isActive: "false",
      isFavorite: "true",
      maxSteps: "12",
      metadataJson: {},
      modelSelection: "openai:gpt-5.4-mini",
      modelSettings: { temperature: 0.2, thinking: "high" },
      name: "Planner",
      skillIds: ["skill-1"],
      thinking: "high",
      toolModes: {
        read_file: "approval",
        missing_tool: "auto",
        send_email: "off",
      },
    })
  })

  it("restores a stored identity color", () => {
    const state = initialAgentFormState(
      { ...agent, metadata: { identity_color: 5, note: "keep" } },
      toolCatalog
    )

    expect(state.identityColor).toBe("5")
    expect(state.metadataJson).toEqual({ identity_color: 5, note: "keep" })
  })
})

describe("validateAgentFormState", () => {
  it("returns entries for required fields and invalid max steps", () => {
    const entries = validateAgentFormState(
      validState({ instructions: " ", maxSteps: "101.5", name: "" })
    )

    expect(entries).toEqual([
      {
        fieldId: "agent-name",
        label: "Name",
        message: "Name is required.",
      },
      {
        fieldId: "agent-instructions",
        label: "Instructions",
        message: "Instructions are required.",
      },
      {
        fieldId: "agent-max-steps",
        label: "Max steps",
        message: "Max steps must be a whole number from 1 to 100.",
      },
    ])
  })

  it("accepts valid state", () => {
    expect(validateAgentFormState(validState())).toEqual([])
  })
})

describe("buildAgentPayload", () => {
  it("builds the full create payload for valid state", () => {
    expect(buildAgentPayload(validState(), "create")).toEqual({
      allowed_agent_ids: ["agent-2"],
      azure_deployment: null,
      code_mode_enabled: false,
      description: "Helps plan launches.",
      instructions: "Use the playbook.",
      is_active: true,
      is_favorite: false,
      max_steps: 25,
      metadata: null,
      model: "gpt-5.4-mini",
      model_provider: "openai",
      model_settings: { temperature: 0.1, thinking: "low" },
      name: "Launch planner",
      skill_ids: ["skill-1"],
      tool_names: ["read_file", "send_email"],
      tool_policies: {
        read_file: "auto",
        send_email: "approval",
      },
    })
  })

  it("builds edit payloads without exposing or changing the system slug", () => {
    expect(buildAgentPayload(validState(), "edit")).toMatchObject({
      name: "Launch planner",
    })
    expect(buildAgentPayload(validState(), "edit")).not.toHaveProperty("slug")
  })

  it("stores a chosen identity color without dropping other metadata", () => {
    expect(
      buildAgentPayload(validState({ identityColor: "3", metadataJson: { note: "keep" } }), "edit")
    ).toMatchObject({
      metadata: { identity_color: 3, note: "keep" },
    })
    expect(
      buildAgentPayload(
        validState({ identityColor: "Auto", metadataJson: { identity_color: 3 } }),
        "edit"
      )
    ).toMatchObject({ metadata: null })
  })

  it("returns the first validation error string for invalid state", () => {
    expect(buildAgentPayload(validState({ name: "" }), "create")).toBe("Name is required.")
    expect(buildAgentPayload(validState({ maxSteps: "0" }), "create")).toBe(
      "Max steps must be a whole number from 1 to 100."
    )
  })
})

describe("isAgentFormDirty", () => {
  it("tracks field-level changes", () => {
    const initial = initialAgentFormState(agent, toolCatalog)

    expect(isAgentFormDirty(initial, initial)).toBe(false)
    expect(isAgentFormDirty({ ...initial, name: "Planner v2" }, initial)).toBe(true)
    expect(isAgentFormDirty({ ...initial, codeModeEnabled: false }, initial)).toBe(true)
  })
})

describe("buildModelOptions", () => {
  it("keeps a saved model override when it is absent from the catalog", () => {
    const catalog: ModelCatalogResponse = {
      providers: [],
      models: [
        {
          id: "openai:gpt-5.4",
          provider: "openai",
          model: "gpt-5.4",
          model_type: "powerful",
          display_name: "GPT-5.4",
          context_window: 128000,
          supports_tools: true,
          supports_thinking: true,
          supports_vision: true,
          supports_structured_output: true,
          default_settings: {},
        },
      ],
      defaults: { agent_model: "openai:gpt-5.4" },
    }

    expect(buildModelOptions(catalog, agent).map((option) => option.value)).toEqual([
      "Default",
      "openai:gpt-5.4-mini",
      "openai:gpt-5.4",
    ])
  })
})

describe("simple model selection", () => {
  it("includes only configured providers that have catalog models", () => {
    expect(buildProviderOptions(modelCatalog)).toEqual([
      { label: "OpenAI", value: "openai" },
      { label: "Anthropic", value: "anthropic" },
      { label: "Google", value: "google" },
    ])
  })

  it("orders available model types and omits types the provider lacks", () => {
    expect(buildModelTypeOptions(modelCatalog, "google")).toEqual([
      {
        description: "Workspace default (OpenAI · GPT-5.6 Luna).",
        label: "Automatic (recommended)",
        value: "automatic",
      },
      {
        description: "Fastest and lowest cost, for simple tasks.",
        label: "Light",
        value: "light",
      },
      {
        description: "Fast and capable, best for most tasks.",
        label: "Standard",
        value: "standard",
      },
      {
        description: "Larger models for complex work, higher cost.",
        label: "Powerful",
        value: "powerful",
      },
    ])
    expect(buildModelTypeOptions(modelCatalog, "anthropic").at(-1)).toEqual({
      description: "The most powerful model available, very high cost.",
      label: "Max",
      value: "max",
    })
  })

  it("omits Automatic when the workspace default is unavailable", () => {
    const catalogWithoutDefault = { ...modelCatalog, defaults: { agent_model: null } }

    expect(
      buildModelTypeOptions(catalogWithoutDefault, "openai").map((option) => option.value)
    ).toEqual(["light", "standard"])
  })

  it("maps model types and Automatic to the stored selection", () => {
    expect(modelSelectionForType(modelCatalog, "openai", "standard")).toBe("openai:gpt-5.6-luna")
    expect(modelSelectionForType(modelCatalog, "anthropic", "light")).toBe(
      "anthropic:claude-haiku-4-5"
    )
    expect(modelSelectionForType(modelCatalog, "google", "light")).toBe(
      "google:gemini-3.5-flash-lite"
    )
    expect(modelSelectionForType(modelCatalog, "openai", "automatic")).toBe("Default")
    expect(buildAgentPayload(validState({ modelSelection: "Default" }), "create")).toMatchObject({
      model: null,
      model_provider: null,
    })
  })

  it("derives Automatic, provider picks, and custom selections", () => {
    expect(simpleSelectionFromModel(modelCatalog, "Default")).toMatchObject({
      modelType: "automatic",
      provider: "openai",
    })
    expect(simpleSelectionFromModel(modelCatalog, "anthropic:claude-sonnet-5")).toMatchObject({
      modelType: "standard",
      provider: "anthropic",
    })
    expect(simpleSelectionFromModel(modelCatalog, "anthropic:claude-opus-4-7")).toEqual({
      modelType: "custom",
      provider: "anthropic",
      selectedLabel: "Custom (Anthropic · Claude Opus 4.7)",
    })
    expect(simpleSelectionFromModel(modelCatalog, "azure:deployment-model")).toEqual({
      modelType: "custom",
      provider: "azure",
      selectedLabel: "Custom (azure:deployment-model)",
    })
  })

  it("keeps the type across providers and falls back to Standard when unavailable", () => {
    expect(modelSelectionForProvider(modelCatalog, "anthropic", "openai:gpt-5.4-nano")).toBe(
      "anthropic:claude-haiku-4-5"
    )
    expect(modelSelectionForProvider(modelCatalog, "google", "anthropic:claude-fable-5")).toBe(
      "google:gemini-3.7-flash"
    )
  })
})
