// apps/web/src/features/tools/types.ts

type ToolEffect = "read" | "write"
type ToolEffectScope = "internal" | "external"
type ToolKind = "function" | "capability"
export type ToolCatalogPolicy = "auto" | "approval"

export type ToolCatalogEntry = {
  name: string
  provider: string
  label: string
  description: string
  kind: ToolKind
  effect: ToolEffect
  effect_scope: ToolEffectScope
  default_policy: ToolCatalogPolicy
  supported_policies: ToolCatalogPolicy[]
  defer_loading: boolean
}

export type ToolCatalogResponse = {
  tools: ToolCatalogEntry[]
}

export type ToolUiFieldFormat = "text" | "multiline" | "markdown" | "bytes" | "datetime" | "boolean"

export type ToolUiField = {
  key: string
  label: string
  format: ToolUiFieldFormat
}

export type ToolUi = {
  icon: string
  running_label: string
  completed_label: string
  failed_label: string
  approval_title: string
  approval_prompt: string
  arg_fields: ToolUiField[]
  result_fields: ToolUiField[]
}

export type ToolPresentationEntry = {
  name: string
  provider: string
  label: string
  effect: ToolEffect
  ui: ToolUi
}

export type ToolPresentationsResponse = {
  tools: ToolPresentationEntry[]
}
