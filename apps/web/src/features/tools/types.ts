// apps/web/src/features/tools/types.ts

import type { ToolFieldColumn, ToolFieldFormat } from "@/components/tool-ui/field-resolution"

type ToolEffect = "read" | "write"
type ToolEffectScope = "internal" | "external"
type ToolEgress = "none" | "provider_query" | "arbitrary_url" | "external_write"
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
  egress: ToolEgress
  default_policy: ToolCatalogPolicy
  supported_policies: ToolCatalogPolicy[]
  defer_loading: boolean
}

export type ToolCatalogResponse = {
  tools: ToolCatalogEntry[]
}

export type ToolUiField = {
  columns?: ToolFieldColumn[]
  key: string
  label: string
  min_rows: number
  format: ToolFieldFormat
  editable: boolean
  placeholder: string
  options: string[]
  secondary: boolean
  entity_kind?: string | null
  depends_on?: string[]
}

export type EntityReferenceValue = Record<string, unknown>

export type EntityChoice = {
  identity: string[]
  value: EntityReferenceValue
  label: string
  description?: string | null
  scope_label?: string | null
  icon?: string | null
}

export type EntityReferenceLookupResponse = {
  entity_kind: string
  choices: EntityChoice[]
  next_cursor?: string | null
}

export type ToolUi = {
  icon: string
  running_label: string
  completed_label: string
  failed_label: string
  approval_title: string
  approval_prompt: string
  approve_label: string
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
