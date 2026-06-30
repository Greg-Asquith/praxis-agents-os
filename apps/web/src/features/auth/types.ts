// apps/web/src/features/auth/types.ts

export type AuthUser = {
  id: string
  email: string
  display_name: string | null
  avatar_url: string | null
  is_active: boolean
  default_workspace_id: string | null
  totp_enabled: boolean
  created_at: string
  updated_at: string
}

type AuthSession = {
  expires_at: string
  twofa_verified: boolean
}

export type AuthResponse = {
  user: AuthUser | null
  session: AuthSession
  requires_twofa: boolean
}

export type AuthIdentity = {
  provider: string
  email: string | null
  email_verified: boolean
  created_at: string
}

export type IdentitiesResponse = {
  has_password: boolean
  identities: AuthIdentity[]
}

export type UpdateCurrentUserRequest = {
  display_name?: string | null
  avatar_url?: string | null
}

export type ChangePasswordRequest = {
  current_password: string
  new_password: string
}

export type TotpSetupResponse = {
  provisioning_uri: string
  secret: string
}

export type TotpEnableResponse = {
  message: string
  backup_codes: string[]
}

export type LoginRequest = {
  email: string
  password: string
}

export type RegisterRequest = {
  email: string
  password: string
  display_name?: string | null
}
