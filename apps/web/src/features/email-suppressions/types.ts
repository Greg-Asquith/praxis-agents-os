// apps/web/src/features/email-suppressions/types.ts

export type EmailSuppression = {
  created_at: string
  created_by_name: string | null
  created_by_user_id: string | null
  email: string
  id: string
  reason: string
  source: string
}

export type EmailSuppressionListResponse = {
  entries: EmailSuppression[]
  limit: number
  offset: number
  total: number
}

export type EmailSuppressionAddRequest = {
  addresses: string[]
  reason: string
}

export type EmailSuppressionAddResponse = {
  added: EmailSuppression[]
  already_listed: string[]
  invalid: string[]
}
