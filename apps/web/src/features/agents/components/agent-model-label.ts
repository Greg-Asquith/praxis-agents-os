// apps/web/src/features/agents/components/agent-model-label.ts

import type { Agent } from "@/features/agents/types"
import type { ModelCatalogResponse } from "@/features/models/types"

export function formatAgentModel(agent: Agent, catalog: ModelCatalogResponse) {
  if (agent.model_provider === "azure" && agent.azure_deployment) {
    return `Azure OpenAI · ${agent.azure_deployment}`
  }

  if (agent.model_provider && agent.model) {
    const qualifiedId = `${agent.model_provider}:${agent.model}`
    return modelDisplayName(catalog, qualifiedId) ?? qualifiedId
  }

  if (catalog.defaults.agent_model) {
    return `Default · ${modelDisplayName(catalog, catalog.defaults.agent_model) ?? catalog.defaults.agent_model}`
  }

  return "Workspace default"
}

export function modelDisplayName(catalog: ModelCatalogResponse, qualifiedId: string) {
  const model = catalog.models.find((item) => item.id === qualifiedId)
  if (!model) {
    return null
  }

  const provider = catalog.providers.find((item) => item.provider === model.provider)
  return `${provider?.display_name ?? model.provider} · ${model.display_name}`
}
