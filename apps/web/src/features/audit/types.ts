// apps/web/src/features/audit/types.ts

// Mirrors apps/api/services/audit_events/enums.py

export type AuditAction = "create" | "read" | "update" | "delete" | "execute" | "enable" | "disable"

export type AuditResourceType =
  | "user"
  | "user_auth"
  | "session"
  | "workspace"
  | "workspace_membership"
  | "invitation"
  | "notification"
  | "agent"
  | "agent_schedule"
  | "agent_schedule_run"

export type AuditStatus = "success" | "failure" | "denied"

// Mirrors apps/api/services/security/enums.py.
export type SecurityEventType =
  | "auth_login_succeeded"
  | "auth_login_failed"
  | "auth_account_locked"
  | "auth_logout_succeeded"
  | "auth_oauth_started"
  | "auth_oauth_succeeded"
  | "auth_oauth_failed"
  | "auth_password_changed"
  | "auth_register_succeeded"
  | "auth_register_failed"
  | "auth_session_refreshed"
  | "auth_session_revoked"
  | "auth_totp_challenge_created"
  | "auth_totp_disabled"
  | "auth_totp_enabled"
  | "auth_totp_failed"
  | "auth_totp_verified"
  | "rate_limit_exceeded"
  | "csrf_validation_failed"
  | "workspace_membership_created"
  | "workspace_membership_updated"
  | "workspace_membership_deleted"
  | "workspace_invitation_created"
  | "workspace_invitation_updated"
  | "workspace_invitation_deleted"
  | "workspace_invitation_accepted"
  | "workspace_invitation_failed"

export const AUDIT_ACTIONS = [
  "create",
  "read",
  "update",
  "delete",
  "execute",
  "enable",
  "disable",
] as const satisfies readonly AuditAction[]

export const AUDIT_RESOURCE_TYPES = [
  "user",
  "user_auth",
  "session",
  "workspace",
  "workspace_membership",
  "invitation",
  "notification",
  "agent",
  "agent_schedule",
  "agent_schedule_run",
] as const satisfies readonly AuditResourceType[]

export const AUDIT_STATUSES = [
  "success",
  "failure",
  "denied",
] as const satisfies readonly AuditStatus[]

export const SECURITY_EVENT_TYPES = [
  "auth_login_succeeded",
  "auth_login_failed",
  "auth_account_locked",
  "auth_logout_succeeded",
  "auth_oauth_started",
  "auth_oauth_succeeded",
  "auth_oauth_failed",
  "auth_password_changed",
  "auth_register_succeeded",
  "auth_register_failed",
  "auth_session_refreshed",
  "auth_session_revoked",
  "auth_totp_challenge_created",
  "auth_totp_disabled",
  "auth_totp_enabled",
  "auth_totp_failed",
  "auth_totp_verified",
  "rate_limit_exceeded",
  "csrf_validation_failed",
  "workspace_membership_created",
  "workspace_membership_updated",
  "workspace_membership_deleted",
  "workspace_invitation_created",
  "workspace_invitation_updated",
  "workspace_invitation_deleted",
  "workspace_invitation_accepted",
  "workspace_invitation_failed",
] as const satisfies readonly SecurityEventType[]

export type AuditEvent = {
  id: string
  workspace_id: string | null
  occurred_at: string
  action: string
  resource_type: string
  resource_id: string | null
  status: string
  summary: string
  actor_type: string
  actor_id: string | null
  actor_user_id: string | null
  actor_display: string | null
  requested_by_user_id: string | null
  details: Record<string, unknown>
  request_id: string | null
  ip_address: string | null
  user_agent: string | null
  created_at: string
}

export type AuditEventsListResponse = {
  events: AuditEvent[]
  total: number
  limit: number
  offset: number
}

export type SecurityEvent = {
  id: string
  occurred_at: string
  event_type: string
  ip_address: string
  endpoint: string | null
  user_email: string | null
  user_agent: string | null
  details: Record<string, unknown>
  request_id: string | null
  created_at: string
}

export type SecurityEventsListResponse = {
  events: SecurityEvent[]
  total: number
  limit: number
  offset: number
}
