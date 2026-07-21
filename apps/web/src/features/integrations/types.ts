// apps/web/src/features/integrations/types.ts

type Connection = {
  id: string
  status: string
}

export type ActiveContextSelectionValue =
  | {
      type: "resource"
      integration_resource_id: string
    }
  | {
      type: "context_group"
      context_group_id: string
    }

type ContextGroupMember = {
  id: string
  connection_id: string
  resource_type: string
  external_id: string
  display_name: string
  enabled: boolean
  availability: string
}

export type IntegrationContextGroup = {
  id: string
  workspace_id: string
  name: string
  created_by_user_id: string | null
  created_at: string
  updated_at: string
  members: ContextGroupMember[]
}

export type ContextGroupListResponse = {
  items: IntegrationContextGroup[]
}

type IntegrationConnection = Connection & {
  provider_key: string
  label: string
}

export type ConnectionListResponse = {
  items: IntegrationConnection[]
  total: number
  limit: number
  offset: number
}

export type IntegrationResource = {
  id: string
  connection_id: string
  provider_key: string
  connection_label: string
  resource_type: string
  external_id: string
  display_name: string
  parent_external_id: string | null
  enabled: boolean
  availability: string
  writable: boolean
  metadata: Record<string, unknown>
  first_seen_at: string
  last_seen_at: string
  removed_at: string | null
}

export type OAuthCallbackResponse = {
  connection: Connection
  next_path: string | null
}
