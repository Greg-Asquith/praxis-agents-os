import { describe, expect, it } from "vitest"

import { formatAgentModel } from "@/features/agents/components/agent-model-label"
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
      provider: "openai",
      supports_structured_output: true,
      supports_thinking: true,
      supports_tools: true,
      supports_vision: true,
    },
  ],
  providers: [{ configured: true, display_name: "OpenAI", model_count: 1, provider: "openai" }],
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
