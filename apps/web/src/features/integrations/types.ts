// apps/web/src/features/integrations/types.ts

type Connection = {
  id: string
  status: string
}

export type OAuthCallbackResponse = {
  connection: Connection
  next_path: string | null
}
