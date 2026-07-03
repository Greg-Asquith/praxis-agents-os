// apps/web/src/features/tools/types.ts

type ToolEffect = "read" | "write"
export type ToolCatalogPolicy = "auto" | "approval"

export type ToolCatalogEntry = {
  name: string
  provider: string
  label: string
  description: string
  effect: ToolEffect
  default_policy: ToolCatalogPolicy
  supported_policies: ToolCatalogPolicy[]
  defer_loading: boolean
}

export type ToolCatalogResponse = {
  tools: ToolCatalogEntry[]
}
