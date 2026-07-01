// apps/web/src/features/models/types.ts

type ModelCatalogProvider = {
  provider: string
  display_name: string
  configured: boolean
  model_count: number
}

type ModelCatalogEntry = {
  id: string
  provider: string
  model: string
  display_name: string
  context_window: number
  supports_tools: boolean
  supports_thinking: boolean
  supports_vision: boolean
  supports_structured_output: boolean
  default_settings: Record<string, unknown>
}

type ModelCatalogDefaults = {
  agent_model: string | null
}

export type ModelCatalogResponse = {
  providers: ModelCatalogProvider[]
  models: ModelCatalogEntry[]
  defaults: ModelCatalogDefaults
}
