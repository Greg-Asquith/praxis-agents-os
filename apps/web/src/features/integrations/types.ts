// apps/web/src/features/integrations/types.ts

type IntegrationOwnerScope = "user" | "workspace"
type IntegrationAuthMode = string

type ConnectionStatus =
  | "auth_pending"
  | "discovery_pending"
  | "needs_resource_selection"
  | "active"
  | "degraded"
  | "error"
  | "revoked"
  | "needs_reauth"

export type IntegrationProvider = {
  provider_key: string
  display_name: string
  auth_modes: IntegrationAuthMode[]
  owner_scope: IntegrationOwnerScope
  oauth_scopes: string[]
  resource_types: string[]
  required_form_fields: string[]
  capability_flags: string[]
  requires_discovery: boolean
  configured: boolean
  configured_auth_modes: Record<string, boolean>
}

type IntegrationCredentialMetadata = {
  auth_mode: string
  secret_reference: string | null
  token_expires_at: string | null
  granted_scopes: string[] | null
  principal_fingerprint: string
  external_principal_label: string | null
  last_refreshed_at: string | null
  last_refresh_error_code: string | null
}

type IntegrationDiscoveryRun = {
  status: "running" | "succeeded" | "failed"
  resources_found: number
  error_code: string | null
  started_at: string
  finished_at: string | null
}

export type IntegrationConnection = {
  id: string
  provider_key: string
  label: string
  owner_scope: IntegrationOwnerScope
  owner_user_id: string | null
  owner_workspace_id: string | null
  status: ConnectionStatus | (string & {})
  status_reason: string | null
  connected_by_user_id: string
  created_at: string
  updated_at: string
  duplicate_of_connection_ids: string[]
  credential: IntegrationCredentialMetadata | null
  latest_discovery_run: IntegrationDiscoveryRun | null
  discovery_in_flight: boolean
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
  connection_owner_scope: IntegrationOwnerScope
  provider_key?: string
  connection_label?: string
  connection_status?: string
}

export type DiscoveryTriggerResponse = {
  job_id: string
}

export type ResourceSelectionResponse = {
  connection_id: string
  enabled_resource_ids: string[]
  status: string
}

export type OAuthConnectResponse = {
  authorization_url: string
  state: string
  connection_id: string
}

export type ConnectionTestResponse = {
  connection_id: string
  status: string
  external_principal_label?: string | null
}

export type ConnectionRefreshResponse = {
  connection_id: string
  status: string
  token_expires_at: string | null
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

type ResolvedContextEntry = {
  integration_resource_id: string
  provider_key: string
  resource_type: string
  external_id: string
  display_name: string
  connection_id: string
  connection_label: string
  connection_status: string
  write_allowed: boolean
}

type UnavailableContextEntry = {
  display_name: string
  provider_key: string
  reason: string
}

export type ActiveContextRead = {
  selection: ActiveContextSelectionValue | null
  entries: ResolvedContextEntry[]
  unavailable: UnavailableContextEntry[]
}

export type ContextGroupWriteRequest = {
  name: string
  resource_ids: string[]
}

export type OAuthCallbackResponse = {
  connection: {
    id: string
    status: string
  }
  next_path: string | null
}
