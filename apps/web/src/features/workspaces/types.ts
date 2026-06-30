// apps/web/src/features/workspaces/types.ts

export type WorkspaceRole = "owner" | "admin" | "member" | "read_only"

export type Workspace = {
  id: string
  slug: string
  name: string
  icon_url: string | null
  is_personal: boolean
  status: string
  current_user_role: WorkspaceRole | null
  created_at: string
  updated_at: string
  deleted: boolean
  deleted_at: string | null
}

export type WorkspacesListResponse = {
  workspaces: Workspace[]
  total: number
  limit: number
  offset: number
}

export type WorkspaceCreateRequest = {
  name: string
  slug?: string | null
  icon_url?: string | null
}

export type WorkspaceUpdateRequest = {
  name?: string | null
  slug?: string | null
  icon_url?: string | null
}

type WorkspaceMembership = {
  id: string
  workspace_id: string
  user_id: string
  role: WorkspaceRole
  user_email: string | null
  user_display_name: string | null
  created_at: string
  updated_at: string
  deleted: boolean
  deleted_at: string | null
}

export type WorkspaceMembershipsListResponse = {
  memberships: WorkspaceMembership[]
  total: number
  limit: number
  offset: number
}

type WorkspaceInvitation = {
  id: string
  workspace_id: string
  email: string
  role: WorkspaceRole
  invited_by: string
  expires_at: string
  accepted_at: string | null
  created_at: string
  updated_at: string
  deleted: boolean
  deleted_at: string | null
}

export type WorkspaceInvitationsListResponse = {
  invitations: WorkspaceInvitation[]
  total: number
  limit: number
  offset: number
}

export type WorkspaceInvitationCreateRequest = {
  email: string
  role: WorkspaceRole
  expires_in_days?: number
}

export type WorkspaceInvitationCreateResponse = {
  invitation: WorkspaceInvitation
  token: string
}
