import { describe, expect, it } from "vitest"

import {
  formatAgentModel,
  formatAgentModelType,
} from "@/features/agents/components/agent-model-label"
import type { ModelCatalogResponse } from "@/features/models/types"

const catalog: ModelCatalogResponse = {
  defaults: { agent_model: "openai:gpt-5.6-luna" },
  models: [
    {
      context_window: 128_000,
      default_settings: {},
      display_name: "GPT-5.6 Luna",
      id: "openai:gpt-5.6-luna",
      model: "gpt-5.6-luna",
      model_type: "standard",
      provider: "openai",
      supports_structured_output: true,
      supports_thinking: true,
      supports_tools: true,
      supports_vision: true,
    },
    {
      context_window: 128_000,
      default_settings: {},
      display_name: "GPT-5.4",
      id: "openai:gpt-5.4",
      model: "gpt-5.4",
      model_type: "powerful",
      provider: "openai",
      supports_structured_output: true,
      supports_thinking: true,
      supports_tools: true,
      supports_vision: true,
    },
  ],
  providers: [
    {
      configured: true,
      display_name: "OpenAI",
      model_count: 1,
      model_type_defaults: { standard: "openai:gpt-5.6-luna" },
      provider: "openai",
    },
    {
      configured: true,
      display_name: "Azure OpenAI",
      model_count: 0,
      model_type_defaults: {},
      provider: "azure",
    },
  ],
}

describe("formatAgentModel", () => {
  it("shows the workspace model name without a redundant Default prefix", () => {
    expect(
      formatAgentModel({ azure_deployment: null, model: null, model_provider: null }, catalog, {
        showDefaultLabel: false,
      })
    ).toBe("OpenAI · GPT-5.6 Luna")
  })

  it("keeps the Default context label for other model pickers", () => {
    expect(
      formatAgentModel({ azure_deployment: null, model: null, model_provider: null }, catalog)
    ).toBe("Default · OpenAI · GPT-5.6 Luna")
  })
})

describe("formatAgentModelType", () => {
  it("shows the workspace default model level", () => {
    expect(
      formatAgentModelType({ azure_deployment: null, model: null, model_provider: null }, catalog)
    ).toBe("OpenAI · Standard")
  })

  it("shows the catalog level for a specific model", () => {
    expect(
      formatAgentModelType(
        { azure_deployment: null, model: "gpt-5.4", model_provider: "openai" },
        catalog
      )
    ).toBe("OpenAI · Powerful")
  })

  it("labels a model outside the catalog as Custom without exposing its name", () => {
    expect(
      formatAgentModelType(
        {
          azure_deployment: "production-deployment",
          model: "deployment-model",
          model_provider: "azure",
        },
        catalog
      )
    ).toBe("Azure OpenAI · Custom")
  })
})
