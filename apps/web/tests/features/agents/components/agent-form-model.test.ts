import { describe, expect, it } from "vitest"

import {
  buildAgentPayload,
  buildModelOptions,
  initialAgentFormState,
  modelSelectionForType,
  setAllTools,
  simpleSelectionFromModel,
  validateAgentFormState,
  type AgentFormState,
} from "@/features/agents/components/agent-form-model"
import { unavailableModeOptions } from "@/features/agents/components/agent-tool-catalog-utils"
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
    workspace_policy: null,
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
    workspace_policy: null,
  },
]

const agent: Agent = {
  id: "agent-1",
  name: "Planner",
  slug: "planner",
  description: "Plans work",
  instructions: "Plan the work carefully.",
  base_instructions: null,
  is_builtin: false,
  workspace_id: "workspace-1",
  created_by: "user-1",
  tool_names: ["read_file", "missing_tool"],
  all_tools: false,
  excluded_tool_names: [],
  tool_policies: { read_file: "approval" },
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
  defaults: { agent_model: "openai:gpt-6-luna" },
  models: [
    catalogModel({ displayName: "GPT-6 Luna", id: "openai:gpt-6-luna", modelType: "standard" }),
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
        standard: "openai:gpt-6-luna",
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
    allTools: false,
    description: "  Helps plan launches.  ",
    identityColor: "Auto",
    instructions: "  Use the playbook.  ",
    isActive: "true",
    isBuiltin: false,
    isFavorite: "false",
    maxSteps: "25",
    metadataJson: {},
    modelSelection: "openai:gpt-5.4-mini",
    modelSettings: { temperature: 0.1 },
    name: "  Launch planner  ",
    thinking: "low",
    toolDefaultPolicies: { read_file: "auto", send_email: "auto" },
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
      allTools: false,
      allowedAgentIds: [],
      azureDeployment: "",
      description: "",
      identityColor: "Auto",
      instructions: "",
      isActive: "true",
      isBuiltin: false,
      isFavorite: "false",
      maxSteps: "20",
      metadataJson: {},
      modelSelection: "Default",
      modelSettings: {},
      name: "",
      thinking: "Default",
      toolDefaultPolicies: { read_file: "auto", send_email: "approval" },
      toolModes: {
        read_file: "off",
        send_email: "off",
      },
    })
  })

  it("round-trips an existing agent into editable state", () => {
    const state = initialAgentFormState(agent, toolCatalog)

    expect(state).toEqual({
      allTools: false,
      allowedAgentIds: ["agent-2"],
      azureDeployment: "",
      description: "Plans work",
      identityColor: "Auto",
      instructions: "Plan the work carefully.",
      isActive: "false",
      isBuiltin: false,
      isFavorite: "true",
      maxSteps: "12",
      metadataJson: {},
      modelSelection: "openai:gpt-5.4-mini",
      modelSettings: { temperature: 0.2, thinking: "high" },
      name: "Planner",
      thinking: "high",
      toolDefaultPolicies: { read_file: "auto", send_email: "approval", missing_tool: "auto" },
      toolModes: {
        read_file: "approval",
        missing_tool: "auto",
        send_email: "off",
      },
    })
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
  it("builds the full create payload, saving only policies that differ from the default", () => {
    expect(buildAgentPayload(validState(), "create")).toEqual({
      all_tools: false,
      allowed_agent_ids: ["agent-2"],
      azure_deployment: null,
      description: "Helps plan launches.",
      excluded_tool_names: [],
      instructions: "Use the playbook.",
      is_active: true,
      is_favorite: false,
      max_steps: 25,
      metadata: null,
      model: "gpt-5.4-mini",
      model_provider: "openai",
      model_settings: { temperature: 0.1, thinking: "low" },
      name: "Launch planner",
      tool_names: ["read_file", "send_email"],
      tool_policies: { send_email: "approval" },
    })
  })

  it("keeps inherited and explicit policies for selected tools missing from the catalog", () => {
    const withHiddenTools: Agent = {
      ...agent,
      tool_names: ["read_file", "inherited_hidden", "explicit_hidden"],
      tool_policies: { read_file: "approval", explicit_hidden: "approval" },
    }
    const state = initialAgentFormState(withHiddenTools, toolCatalog)

    // objectContaining compares each property exactly, unlike toMatchObject.
    expect(buildAgentPayload({ ...state, name: "Renamed" }, "edit")).toEqual(
      expect.objectContaining({
        tool_names: ["read_file", "inherited_hidden", "explicit_hidden"],
        tool_policies: { read_file: "approval", explicit_hidden: "approval" },
      })
    )
  })

  it("records a tool turned off after enabling all tools as an exclusion", () => {
    const enabled = setAllTools(validState({ toolModes: {} }), toolCatalog, true)
    const state = { ...enabled, toolModes: { ...enabled.toolModes, send_email: "off" as const } }

    expect(buildAgentPayload(state, "create")).toEqual(
      expect.objectContaining({
        all_tools: true,
        excluded_tool_names: ["send_email"],
        tool_names: [],
        tool_policies: null,
      })
    )
  })

  it("keeps a hidden approval override and clears exclusions when enabling all tools", () => {
    const narrow: Agent = {
      ...agent,
      tool_names: ["read_file", "web_search"],
      tool_policies: { web_search: "approval" },
    }
    const state = initialAgentFormState(narrow, toolCatalog)

    expect(buildAgentPayload(setAllTools(state, toolCatalog, true), "edit")).toEqual(
      expect.objectContaining({
        all_tools: true,
        excluded_tool_names: [],
        tool_names: [],
        tool_policies: { web_search: "approval" },
      })
    )
  })

  it("does not exclude catalog tools missing from an older all-tools snapshot", () => {
    const allTools: Agent = {
      ...agent,
      all_tools: true,
      tool_names: ["read_file", "missing_tool"],
      excluded_tool_names: ["retired_tool"],
      tool_policies: null,
    }
    const state = initialAgentFormState(allTools, toolCatalog)

    expect(buildAgentPayload({ ...state, name: "Renamed" }, "edit")).toEqual(
      expect.objectContaining({
        all_tools: true,
        excluded_tool_names: ["retired_tool"],
        tool_names: [],
        tool_policies: null,
      })
    )
  })

  it("sends only the built-in agent's editable settings, allowing empty instructions", () => {
    const payload = buildAgentPayload(
      validState({ instructions: "  ", isBuiltin: true, name: "" }),
      "edit"
    )

    expect(payload).toEqual({
      azure_deployment: null,
      instructions: "",
      is_active: true,
      is_favorite: false,
      model: "gpt-5.4-mini",
      model_provider: "openai",
      model_settings: { temperature: 0.1, thinking: "low" },
      tool_policies: { send_email: "approval" },
    })
  })

  it("keeps a built-in agent's approval override for an unavailable tool", () => {
    const builtin: Agent = {
      ...agent,
      all_tools: true,
      is_builtin: true,
      tool_names: ["read_file"],
      tool_policies: { fetch_url: "approval" },
    }
    const state = initialAgentFormState(builtin, toolCatalog)

    expect(unavailableModeOptions(state.toolModes["fetch_url"], false)).toEqual(["approval"])
    expect(buildAgentPayload(state, "edit")).toEqual(
      expect.objectContaining({ tool_policies: { fetch_url: "approval" } })
    )
  })

  it("builds edit payloads without exposing or changing the system slug", () => {
    expect(buildAgentPayload(validState(), "edit")).toMatchObject({
      name: "Launch planner",
    })
    expect(buildAgentPayload(validState(), "edit")).not.toHaveProperty("slug")
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
  it("maps model types and Automatic to the stored selection", () => {
    expect(modelSelectionForType(modelCatalog, "openai", "standard")).toBe("openai:gpt-6-luna")
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
})
