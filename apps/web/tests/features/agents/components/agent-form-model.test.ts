import { describe, expect, it } from "vitest"

import {
  buildAgentPayload,
  buildModelOptions,
  initialAgentFormState,
  isAgentFormDirty,
  validateAgentFormState,
  type AgentFormState,
} from "@/features/agents/components/agent-form-model"
import type { Agent } from "@/features/agents/types"
import type { ModelCatalogResponse } from "@/features/models/types"
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

function validState(overrides: Partial<AgentFormState> = {}): AgentFormState {
  return {
    allowedAgentIds: ["agent-2"],
    azureDeployment: "",
    description: "  Helps plan launches.  ",
    instructions: "  Use the playbook.  ",
    isActive: "true",
    isFavorite: "false",
    maxSteps: "25",
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
      description: "",
      instructions: "",
      isActive: "true",
      isFavorite: "false",
      maxSteps: "20",
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
      description: "Plans work",
      instructions: "Plan the work carefully.",
      isActive: "false",
      isFavorite: "true",
      maxSteps: "12",
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
      description: "Helps plan launches.",
      instructions: "Use the playbook.",
      is_active: true,
      is_favorite: false,
      max_steps: 25,
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
